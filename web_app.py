"""FastMSR — an open-source Mortgage Servicing Rights management system.

A server-side, HTMX-driven FastHTML app: loan-tape portfolios, a real (simple)
DCF MSR valuation engine with rate-shock scenarios, a MOCK Freddie Mac
Cash-Released XChange (CRX) competitive-bidding exchange, servicing-transfer
workflows, compliance/risk and a full RBAC audit trail.

Run:
    python web_app.py            # http://localhost:5008

Login: admin@fastmsr.example / FastMSR2026$  (override via .env, see .env.sample)

>>> Freddie Mac CRX integration is SIMULATED — no external connection. <<<
"""
from __future__ import annotations

import os
import secrets
import logging

from dotenv import load_dotenv
load_dotenv()

from fasthtml.common import (
    fast_app, serve, Div, H1, P, A, Form, Input, Button, Span,
    NotStr, RedirectResponse, Style, Link, Title,
)
from starlette.responses import Response

import db
import crx
import valuation as val
from web.layout import LAYOUT_CSS, page
from web import views

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s")
logger = logging.getLogger("fastmsr")

VALID_EMAIL = os.getenv("FASTMSR_ADMIN_EMAIL", "admin@fastmsr.example")
VALID_PASSWORD = os.getenv("FASTMSR_ADMIN_PASSWORD", "FastMSR2026$")
ENV_LABEL = os.getenv("FASTMSR_ENV_LABEL", "Demo · Synthetic")
SECRET = os.getenv("FASTMSR_SECRET", secrets.token_hex(32))
PORT = int(os.getenv("FASTMSR_PORT", "5008"))

app, rt = fast_app(live=False, pico=False, secret_key=SECRET, hdrs=[Style(LAYOUT_CSS)])


# --- auth / role helpers ----------------------------------------------------

def _user(session):
    return session.get("user")


def _role(session) -> str:
    return session.get("role") or "Admin"


def _guard_page(session, active, builder):
    if not _user(session):
        return RedirectResponse("/login", status_code=303)
    content = builder() if callable(builder) else builder
    if not isinstance(content, tuple):
        content = (content,)
    return page(active, ENV_LABEL, _role(session), _user(session), *content)


def _perm(session, action, entity="", entity_id=0, detail="") -> bool:
    """RBAC check + audit. On denial raises an in-app alert for visibility."""
    role = _role(session)
    ok = db.guard(role, action, entity, entity_id, detail)
    if not ok:
        db.alert("warn", "risk", f"Permission denied: role “{role}” cannot perform {action}.")
    return ok


def _login_card(error: str = "", email: str = ""):
    return Title("FastMSR — Sign in"), Style(LAYOUT_CSS), Div(
        Form(
            H1(Span(cls="brand-dot"), NotStr("&nbsp;"), "FastMSR"),
            P("Mortgage Servicing Rights management · Freddie Mac CRX (simulated)"),
            Input(name="email", type="email", placeholder="Email", value=email, required=True),
            Input(name="password", type="password", placeholder="Password", required=True),
            P(error, cls="error") if error else None,
            Button("Sign in", cls="btn primary", type="submit"),
            P(NotStr("Demo: <code>admin@fastmsr.example</code> / <code>FastMSR2026$</code>"), cls="hint"),
            method="post", action="/login", cls="login-card"),
        cls="login-wrap")


# --- auth routes ------------------------------------------------------------

@rt("/login")
def get(session):
    if _user(session):
        return RedirectResponse("/", status_code=303)
    return _login_card()


@rt("/login")
def post(session, email: str = "", password: str = ""):
    if email.strip().lower() == VALID_EMAIL.lower() and password == VALID_PASSWORD:
        session["user"] = email.strip().lower()
        session["role"] = "Admin"
        return RedirectResponse("/", status_code=303)
    return _login_card("Invalid email or password.", email)


@rt("/logout")
def get(session):
    session.pop("user", None)
    return RedirectResponse("/login", status_code=303)


@rt("/role")
def post(session, role: str = "Admin", next: str = "/"):
    if not _user(session):
        return RedirectResponse("/login", status_code=303)
    if role in db.ROLES:
        prev = session.get("role")
        session["role"] = role
        if prev != role:
            db.audit(role, "role.switch", "session", 0, "allowed", f"Switched role from {prev} to {role}.")
    return RedirectResponse(next or "/", status_code=303)


@rt("/healthz")
def get():
    return Response("ok")


# --- overview ---------------------------------------------------------------

@rt("/")
def get(session):
    return _guard_page(session, "dashboard", views.dashboard)


@rt("/alerts")
def get(session):
    return _guard_page(session, "alerts", views.alerts_view)


@rt("/alerts/read")
def post(session):
    if not _user(session):
        return RedirectResponse("/login", status_code=303)
    db.mark_alerts_read()
    return RedirectResponse("/alerts", status_code=303)


# --- portfolios -------------------------------------------------------------

@rt("/portfolios")
def get(session):
    return _guard_page(session, "portfolios", views.portfolios_list)


@rt("/portfolios/{pid}")
def get(session, pid: int):
    return _guard_page(session, "portfolios", lambda: views.portfolio_detail(pid))


@rt("/portfolios/{pid}/import")
def get(session, pid: int):
    return _guard_page(session, "portfolios", lambda: views.import_form(pid))


@rt("/portfolios/{pid}/import")
def post(session, pid: int, csv: str = ""):
    if not _user(session):
        return RedirectResponse("/login", status_code=303)
    if not _perm(session, "portfolio.import", "portfolio", pid):
        return RedirectResponse(f"/portfolios/{pid}", status_code=303)
    n = _import_csv(pid, csv)
    db.alert("info", "risk", f"Imported {n} loan(s) into portfolio #{pid}; QC re-run.")
    db.audit(_role(session), "portfolio.import", "portfolio", pid, "allowed", f"Imported {n} loans via CSV.")
    return RedirectResponse(f"/portfolios/{pid}", status_code=303)


def _import_csv(pid: int, text: str) -> int:
    import seed as _seed  # reuse the QC ruleset
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    if not lines:
        return 0
    header = [h.strip().lower() for h in lines[0].split(",")]
    count = 0
    for ln in lines[1:]:
        parts = [p.strip() for p in ln.split(",")]
        if len(parts) < 4:
            continue
        row = dict(zip(header, parts))
        try:
            loan = {
                "portfolio_id": pid,
                "loan_number": row.get("loan_number") or f"IMP-{count}",
                "borrower_state": row.get("state", "NA"),
                "upb": float(row.get("upb", 0) or 0),
                "orig_balance": float(row.get("upb", 0) or 0),
                "note_rate": float(row.get("note_rate", 0.065) or 0.065),
                "servicing_fee_rate": float(row.get("servicing_fee_rate", 0.0025) or 0.0025),
                "ltv": float(row.get("ltv", 80) or 80),
                "fico": int(float(row.get("fico", 720) or 720)),
                "dti": float(row.get("dti", 36) or 36),
                "product_type": row.get("product_type", "Fixed 30"),
                "escrow": int(float(row.get("escrow", 1) or 1)),
                "delinquency_status": row.get("delinquency", "Current"),
                "investor": row.get("investor", "Freddie Mac"),
                "remaining_term": int(float(row.get("remaining_term", 360) or 360)),
                "age_months": 0,
                "mers_min": row.get("mers_min", "100" + "0" * 15),
                "created": db.scalar("SELECT datetime('now')"),
            }
        except (ValueError, TypeError):
            continue
        with db.cursor() as conn:
            cols = ",".join(loan.keys())
            ph = ",".join("?" * len(loan))
            conn.execute(f"INSERT INTO loans({cols}) VALUES ({ph})", tuple(loan.values()))
            lid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        for rule, sev, msg in _seed._qc(lid, loan):
            with db.cursor() as conn:
                conn.execute("INSERT INTO qc_flags(loan_id,rule,severity,message,created)"
                             " VALUES (?,?,?,?,datetime('now'))", (lid, rule, sev, msg))
        count += 1
    return count


@rt("/loans/{lid}")
def get(session, lid: int):
    return _guard_page(session, "portfolios", lambda: views.loan_detail(lid))


# --- valuation --------------------------------------------------------------

@rt("/valuation")
def get(session, pid: int = 0, cpr: float = 0.08, default_rate: float = 0.005,
        discount_rate: float = 0.10, servicing_cost: float = 85.0):
    if _user(session) and pid:
        # persist a mark so the MTM history reflects re-valuation
        loans = db.loans(pid)
        if loans:
            a = val.Assumptions(cpr=cpr, default_rate=default_rate,
                                discount_rate=discount_rate, servicing_cost=servicing_cost)
            db.guard(_role(session), "valuation.run", "portfolio", pid, "Recomputed MSR valuation.")
    return _guard_page(session, "valuation",
                       lambda: views.valuation_view(pid or None, cpr, default_rate, discount_rate, servicing_cost))


@rt("/valuation/export")
def get(session, pid: int = 1, cpr: float = 0.08, default_rate: float = 0.005,
        discount_rate: float = 0.10, servicing_cost: float = 85.0):
    if not _user(session):
        return RedirectResponse("/login", status_code=303)
    csv = views.valuation_export(pid, cpr, default_rate, discount_rate, servicing_cost)
    return Response(csv, media_type="text/csv",
                    headers={"Content-Disposition": f"attachment; filename=msr-valuation-pf{pid}.csv"})


# --- CRX exchange -----------------------------------------------------------

@rt("/crx")
def get(session):
    return _guard_page(session, "crx", views.crx_list)


@rt("/crx/new")
def get(session):
    return _guard_page(session, "crx", views.crx_new_form)


@rt("/crx/loan-options")
def get(session, pid: int = 1):
    if not _user(session):
        return Response("Unauthorized", status_code=401)
    return views._loan_options(pid)


@rt("/crx/new")
def post(session, name: str = "", pid: int = 1, loan_ids: list[int] = None):
    if not _user(session):
        return RedirectResponse("/login", status_code=303)
    if not _perm(session, "crx.create", "crx"):
        return RedirectResponse("/crx", status_code=303)
    sel = loan_ids or db.loan_ids(pid)[:5]
    if isinstance(sel, int):
        sel = [sel]
    cid = db.create_crx_contract(name or "CRX Execution", "Predictive Capital Servicing", pid, [int(x) for x in sel])
    db.audit(_role(session), "crx.create", "crx", cid, "allowed", f"Created {name} with {len(sel)} loans.")
    return RedirectResponse(f"/crx/{cid}", status_code=303)


@rt("/crx/{cid}")
def get(session, cid: int):
    return _guard_page(session, "crx", lambda: views.crx_detail(cid))


@rt("/crx/{cid}/run")
def post(session, cid: int, excluded: list[str] = None):
    if not _user(session):
        return RedirectResponse("/login", status_code=303)
    if not _perm(session, "crx.bid", "crx", cid):
        return RedirectResponse(f"/crx/{cid}", status_code=303)
    # Checkbox semantics: a checked box means "included". Excluded = pool - checked.
    included = set(excluded or ([excluded] if isinstance(excluded, str) else []))
    excl = [s for s in db.SERVICER_POOL if s not in included]
    with db.cursor() as conn:
        conn.execute("UPDATE crx_contracts SET excluded=? WHERE id=?", (",".join(excl), cid))
    bids = crx.run_auction(cid)
    winner = next((b for b in bids if b["won"]), None)
    if winner:
        db.alert("info", "bid", f"CRX #{cid}: {winner['servicer']} leads at {winner['srp_bps']:.0f} bps SRP.")
    db.audit(_role(session), "crx.bid", "crx", cid, "allowed",
             f"Ran auction; {len(excl)} servicer(s) excluded.")
    return RedirectResponse(f"/crx/{cid}", status_code=303)


@rt("/crx/{cid}/award")
def post(session, cid: int, bid_id: int = 0):
    if not _user(session):
        return RedirectResponse("/login", status_code=303)
    if not _perm(session, "crx.award", "crx", cid):
        return RedirectResponse(f"/crx/{cid}", status_code=303)
    db.award_bid(cid, bid_id)
    bid = db.one("SELECT * FROM crx_bids WHERE id=?", (bid_id,))
    if bid:
        db.alert("info", "bid", f"CRX #{cid} awarded to {bid['servicer']} at {bid['srp_bps']:.0f} bps SRP.")
    db.audit(_role(session), "crx.award", "crx", cid, "allowed", "Awarded winning bid.")
    return RedirectResponse(f"/crx/{cid}", status_code=303)


@rt("/crx/{cid}/transfer")
def post(session, cid: int):
    if not _user(session):
        return RedirectResponse("/login", status_code=303)
    if not _perm(session, "crx.award", "crx", cid):
        return RedirectResponse(f"/crx/{cid}", status_code=303)
    c = db.crx_contract(cid)
    bid = db.one("SELECT * FROM crx_bids WHERE id=?", (c.get("awarded_bid_id") or 0,))
    with db.cursor() as conn:
        conn.execute(
            "INSERT INTO transfers(contract_id,portfolio_id,transferor,transferee,kind,status,"
            "loan_count,upb,effective_date,mers_batch,created) VALUES "
            "(?,?,?,?, 'Concurrent (CRX)', 'Initiated', ?, ?, date('now','+30 day'), ?, datetime('now'))",
            (cid, c["portfolio_id"], c["seller"], bid["servicer"] if bid else "TBD",
             c["loan_count"], c["upb"], "MERS-BATCH-" + str(cid).zfill(6)))
        tid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    for name, exhibit in crx.DOC_CHECKLIST:
        with db.cursor() as conn:
            conn.execute("INSERT INTO transfer_docs(transfer_id,name,exhibit,status,version,updated)"
                         " VALUES (?,?,?, 'Missing', 1, datetime('now'))", (tid, name, exhibit))
    db.transfer_event(tid, "status", "Concurrent transfer initiated from CRX award.")
    db.set_crx_status(cid, "Funded")
    db.alert("info", "transfer", f"Concurrent servicing transfer T-{tid} initiated from CRX #{cid}.")
    db.audit(_role(session), "transfer.advance", "transfer", tid, "allowed", "Initiated concurrent transfer.")
    return RedirectResponse(f"/transfers/{tid}", status_code=303)


# --- transfers --------------------------------------------------------------

@rt("/transfers")
def get(session):
    return _guard_page(session, "transfers", views.transfers_list)


@rt("/transfers/{tid}")
def get(session, tid: int):
    return _guard_page(session, "transfers", lambda: views.transfer_detail(tid))


@rt("/transfers/{tid}/advance")
def post(session, tid: int):
    if not _user(session):
        return RedirectResponse("/login", status_code=303)
    if not _perm(session, "transfer.advance", "transfer", tid):
        return RedirectResponse(f"/transfers/{tid}", status_code=303)
    nxt = db.advance_transfer(tid)
    db.audit(_role(session), "transfer.advance", "transfer", tid, "allowed", f"Advanced to {nxt}.")
    return RedirectResponse(f"/transfers/{tid}", status_code=303)


@rt("/transfers/{tid}/doc")
def post(session, tid: int, doc_id: int = 0, status: str = "Imaged"):
    if not _user(session):
        return RedirectResponse("/login", status_code=303)
    if not _perm(session, "transfer.doc", "transfer", tid):
        return RedirectResponse(f"/transfers/{tid}", status_code=303)
    db.set_doc_status(doc_id, status)
    return RedirectResponse(f"/transfers/{tid}", status_code=303)


@rt("/transfers/{tid}/resolve")
def post(session, tid: int, exc_id: int = 0):
    if not _user(session):
        return RedirectResponse("/login", status_code=303)
    if not _perm(session, "transfer.advance", "transfer", tid):
        return RedirectResponse(f"/transfers/{tid}", status_code=303)
    with db.cursor() as conn:
        conn.execute("UPDATE exceptions SET status='Resolved' WHERE id=?", (exc_id,))
    db.transfer_event(tid, "exception", "Exception resolved.")
    db.audit(_role(session), "transfer.advance", "transfer", tid, "allowed", "Resolved exception.")
    return RedirectResponse(f"/transfers/{tid}", status_code=303)


# --- compliance / audit / guide ---------------------------------------------

@rt("/compliance")
def get(session):
    return _guard_page(session, "compliance", views.compliance_view)


@rt("/compliance/item")
def post(session, item_id: int = 0, status: str = "Open"):
    if not _user(session):
        return RedirectResponse("/login", status_code=303)
    if not _perm(session, "compliance.signoff", "compliance", item_id):
        return RedirectResponse("/compliance", status_code=303)
    db.set_compliance_status(item_id, status)
    db.audit(_role(session), "compliance.signoff", "compliance", item_id, "allowed", f"Set status {status}.")
    return RedirectResponse("/compliance", status_code=303)


@rt("/audit")
def get(session):
    return _guard_page(session, "audit", views.audit_view)


@rt("/guide")
def get(session):
    return _guard_page(session, "guide", views.guide_view)


# --- boot -------------------------------------------------------------------

def _ensure_db():
    if not db.db_exists():
        logger.info("No database found — seeding synthetic data…")
        import seed
        seed.build()


_ensure_db()

if __name__ == "__main__":
    logger.info("FastMSR on http://localhost:%s  (login %s)", PORT, VALID_EMAIL)
    serve(port=PORT, reload=os.getenv("FASTMSR_RELOAD", "0") == "1")
