"""Generate a fully synthetic FastMSR database.

Deterministic (fixed RNG seed): every run produces the same demo book — no real
loans, borrowers, servicers or PII. Loan numbers, MERS MINs and servicer bids
are all fabricated.

    python seed.py            # builds ./fastmsr.sqlite (or $FASTMSR_DB)

Re-running drops and rebuilds every table.
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta

import db
import crx
import valuation as val

RNG = random.Random(20260718)
NOW = datetime(2026, 7, 18, 9, 0, 0)

STATES = ["CA", "TX", "FL", "NY", "GA", "NC", "AZ", "WA", "CO", "OH", "PA", "IL", "NV", "NJ"]

PORTFOLIOS = [
    ("Sunbelt Conventional 2025-A", "Predictive Capital Servicing", "Freddie Mac", "Undecided",
     "Retail-originated conforming production, Q1-Q2 2025 vintage."),
    ("Coastal Jumbo Retained", "Predictive Capital Servicing", "Portfolio", "Retain",
     "High-balance retained servicing; strong credit, low incentive to refi."),
    ("Correspondent Bulk 2024-C", "Aggregator Bulk Desk", "Fannie Mae", "Release",
     "Seasoned correspondent bulk acquired for servicing-released re-sale."),
]


def _dt(days_ago: float) -> str:
    return (NOW - timedelta(days=days_ago, hours=RNG.randint(0, 9))).strftime("%Y-%m-%d %H:%M:%S")


def _date(days_from_now: float) -> str:
    return (NOW + timedelta(days=days_from_now)).strftime("%Y-%m-%d")


def _min() -> str:
    return "100" + "".join(str(RNG.randint(0, 9)) for _ in range(15)) + str(RNG.randint(0, 9))


def _loan_number(i: int) -> str:
    return f"PCS-{2025000 + i}"


def _make_loan(pf_id: int, i: int, profile: str, investor: str):
    if profile == "conventional":
        upb = round(RNG.uniform(180_000, 480_000), 2)
        note = round(RNG.uniform(0.0575, 0.0725), 5)
        fico = RNG.randint(680, 790)
        ltv = round(RNG.uniform(62, 95), 1)
        product = RNG.choice(["Fixed 30", "Fixed 30", "Fixed 15", "ARM 7/6", "Home Possible"])
    elif profile == "jumbo":
        upb = round(RNG.uniform(720_000, 1_450_000), 2)
        note = round(RNG.uniform(0.0525, 0.0625), 5)
        fico = RNG.randint(740, 815)
        ltv = round(RNG.uniform(55, 78), 1)
        product = RNG.choice(["Fixed 30", "Fixed 15", "ARM 7/6", "ARM 5/6"])
    else:  # correspondent bulk, seasoned, some DQ
        upb = round(RNG.uniform(140_000, 360_000), 2)
        note = round(RNG.uniform(0.0625, 0.0785), 5)
        fico = RNG.randint(640, 760)
        ltv = round(RNG.uniform(70, 97), 1)
        product = RNG.choice(["Fixed 30", "Fixed 30", "Home Possible", "ARM 5/6"])

    age = RNG.randint(3, 30) if profile != "correspondent" else RNG.randint(18, 48)
    rem = (360 if "30" in product or "ARM" in product or product == "Home Possible" else 180) - age
    dq = "Current"
    if profile == "correspondent" and RNG.random() < 0.18:
        dq = RNG.choice(["30 DPD", "30 DPD", "60 DPD", "90+ DPD"])
    svc_fee = 0.0025 if product != "Home Possible" else 0.00375
    return {
        "portfolio_id": pf_id,
        "loan_number": _loan_number(i),
        "borrower_state": RNG.choice(STATES),
        "upb": upb,
        "orig_balance": round(upb * RNG.uniform(1.0, 1.12), 2),
        "note_rate": note,
        "servicing_fee_rate": svc_fee,
        "ltv": ltv,
        "fico": fico,
        "dti": round(RNG.uniform(24, 46), 1),
        "product_type": product,
        "escrow": 1 if RNG.random() < 0.8 else 0,
        "delinquency_status": dq,
        "investor": investor,
        "remaining_term": max(rem, 60),
        "age_months": age,
        "mers_min": _min(),
        "created": _dt(RNG.randint(30, 400)),
    }


def _qc(loan_id: int, ln: dict):
    """Simple eligibility / data-quality rules."""
    out = []
    if ln["ltv"] > 95:
        out.append(("LTV > 95%", "Warning", "LTV above conventional limit without MI evidence."))
    if ln["fico"] < 660:
        out.append(("FICO < 660", "Warning", "Sub-660 FICO — verify compensating factors."))
    if ln["delinquency_status"] in ("60 DPD", "90+ DPD"):
        out.append(("Delinquent", "Error", f"Loan is {ln['delinquency_status']} — ineligible for standard CRX delivery."))
    if ln["escrow"] == 0 and ln["ltv"] > 80:
        out.append(("Escrow waiver > 80 LTV", "Warning", "Escrow waived above 80% LTV — confirm investor overlay."))
    if not ln["mers_min"] or len(ln["mers_min"]) != 18:
        out.append(("MERS MIN", "Error", "MERS MIN missing or malformed (must be 18 digits)."))
    return out


def build():
    db.init_schema()
    with db.cursor() as conn:
        for t in ("audit_log", "alerts", "compliance_items", "exceptions",
                  "transfer_events", "transfer_docs", "transfers", "crx_bids",
                  "crx_contract_loans", "crx_contracts", "valuations", "qc_flags",
                  "loans", "portfolios"):
            conn.execute(f"DELETE FROM {t}")

    profiles = ["conventional", "jumbo", "correspondent"]
    counts = [7, 5, 6]
    loan_i = 1
    pf_ids = []
    for (name, seller, investor, strategy, notes), profile, n in zip(PORTFOLIOS, profiles, counts):
        with db.cursor() as conn:
            conn.execute(
                "INSERT INTO portfolios(name,seller,investor,strategy,notes,created)"
                " VALUES (?,?,?,?,?,?)",
                (name, seller, investor, strategy, notes, _dt(RNG.randint(60, 300))))
            pid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        pf_ids.append(pid)
        for _ in range(n):
            ln = _make_loan(pid, loan_i, profile, investor)
            loan_i += 1
            with db.cursor() as conn:
                cols = ",".join(ln.keys())
                ph = ",".join("?" * len(ln))
                conn.execute(f"INSERT INTO loans({cols}) VALUES ({ph})", tuple(ln.values()))
                lid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            for rule, sev, msg in _qc(lid, ln):
                with db.cursor() as conn:
                    conn.execute(
                        "INSERT INTO qc_flags(loan_id,rule,severity,message,created)"
                        " VALUES (?,?,?,?,datetime('now'))", (lid, rule, sev, msg))

    # --- MSR valuation mark-to-market history (last 6 months) ---------------
    base = val.Assumptions()
    for pid in pf_ids:
        loans = db.loans(pid)
        for k, months_ago in enumerate([5, 4, 3, 2, 1, 0]):
            # Nudge discount + CPR across the months to create a value trend.
            a = val.Assumptions(
                cpr=round(0.07 + 0.004 * (5 - months_ago) + RNG.uniform(-0.003, 0.003), 4),
                default_rate=base.default_rate,
                discount_rate=round(0.098 + 0.002 * (5 - months_ago), 4),
                servicing_cost=base.servicing_cost,
                ancillary=base.ancillary)
            r = val.value_portfolio(loans, a)
            as_of = (NOW - timedelta(days=30 * months_ago)).strftime("%Y-%m-%d")
            db.save_valuation("portfolio", pid, as_of, r.msr_value, r.msr_multiple, r.upb, a.as_dict())

    # --- one CRX execution mid-flight on the Sunbelt book -------------------
    sunbelt = pf_ids[0]
    sel = db.loan_ids(sunbelt)[:5]
    cid = db.create_crx_contract("CRX-EXE-2601 · Sunbelt Cash-Released",
                                 "Predictive Capital Servicing", sunbelt, sel)
    crx.run_auction(cid)
    bids = db.crx_bids(cid)
    winner = next((b for b in bids if b["won"]), None)
    if winner:
        db.award_bid(cid, winner["id"])
        db.alert("info", "bid",
                 f"CRX auction awarded: {winner['servicer']} won at {winner['srp_bps']:.0f} bps SRP.")

    # --- a concurrent (CRX) transfer + a standalone transfer ----------------
    _seed_transfer(cid, sunbelt, "Predictive Capital Servicing",
                   winner["servicer"] if winner else "Newrez",
                   "Concurrent (CRX)", db.crx_contract(cid)["upb"], len(sel),
                   status="Data Validation", with_exception=True)
    _seed_transfer(None, pf_ids[2], "Aggregator Bulk Desk", "Mr. Cooper",
                   "Standalone", db.portfolio(pf_ids[2])["upb"],
                   db.portfolio(pf_ids[2])["loan_count"], status="Boarding",
                   with_exception=False)

    _seed_compliance()
    _seed_alerts(pf_ids)
    _seed_audit()
    print("Seeded FastMSR:",
          f"{len(pf_ids)} portfolios, {loan_i-1} loans, 1 CRX auction, 2 transfers.")


def _seed_transfer(cid, pid, transferor, transferee, kind, upb, n, status, with_exception):
    with db.cursor() as conn:
        conn.execute(
            "INSERT INTO transfers(contract_id,portfolio_id,transferor,transferee,kind,status,"
            "loan_count,upb,effective_date,mers_batch,created) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (cid, pid, transferor, transferee, kind, status, n, upb,
             _date(RNG.randint(20, 45)), "MERS-BATCH-" + str(RNG.randint(100000, 999999)),
             _dt(RNG.randint(3, 20))))
        tid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    flow = [s for s in db.TRANSFER_STATUSES if s != "Exception"]
    reached = flow.index(status) if status in flow else 0
    for s in flow[:reached + 1]:
        db.transfer_event(tid, "status", f"Entered <strong>{s}</strong>.")

    for name, exhibit in crx.DOC_CHECKLIST:
        # Earlier stages => fewer finalized docs.
        r = RNG.random()
        st = "Final" if r < 0.45 + 0.08 * reached else ("Imaged" if r < 0.8 else "Missing")
        with db.cursor() as conn:
            conn.execute(
                "INSERT INTO transfer_docs(transfer_id,name,exhibit,status,version,updated)"
                " VALUES (?,?,?,?,?,datetime('now'))",
                (tid, name, exhibit, st, RNG.randint(1, 3)))

    db.transfer_event(tid, "notification",
                      "Investor notice delivered to transferee; borrower letters scheduled.")
    if with_exception:
        with db.cursor() as conn:
            conn.execute(
                "INSERT INTO exceptions(transfer_id,kind,message,status,created)"
                " VALUES (?,?,?, 'Open', datetime('now'))",
                (tid, "Data Discrepancy",
                 "Escrow balance on 1 loan differs from tape by $412.18 — reconcile before boarding."))
        db.transfer_event(tid, "exception",
                          "Exception opened: escrow balance mismatch on loan PCS-2025003.")


def _seed_compliance():
    items = [
        ("Freddie Guide", "Seller/Servicer eligibility current (Guide Ch. 2101)", "Guide 2101.1", "Satisfied"),
        ("Freddie Guide", "Cash-Released XChange contract terms accepted", "Guide 6305", "Satisfied"),
        ("Freddie Guide", "Transfer of Servicing delivery per Exhibit 28A", "Exhibit 28A", "Open"),
        ("Freddie Guide", "MERS transfers registered within 2 business days", "Guide 1301.11", "Open"),
        ("CFPB", "Servicing transfer borrower notice ≥15 days pre-effective", "12 CFR 1024.33", "Open"),
        ("CFPB", "No payment treated late for 60 days post-transfer", "12 CFR 1024.33(c)", "Satisfied"),
        ("CFPB", "Loss-mitigation applications transferred to new servicer", "12 CFR 1024.38", "Open"),
        ("Internal", "Concentration limits reviewed (geo & servicer)", "RISK-CONC-01", "Open"),
        ("Internal", "MSR hedge coverage recorded for rate exposure", "RISK-HEDGE-02", "Open"),
    ]
    for cat, item, ref, status in items:
        owner = {"Freddie Guide": "Seller/Transferor", "CFPB": "Compliance Officer",
                 "Internal": "Portfolio Manager"}[cat]
        with db.cursor() as conn:
            conn.execute(
                "INSERT INTO compliance_items(category,item,reference,status,owner_role,updated)"
                " VALUES (?,?,?,?,?,datetime('now'))", (cat, item, ref, status, owner))


def _seed_alerts(pf_ids):
    db.alert("warn", "transfer",
             "Transfer T-1 has an open escrow discrepancy exception blocking boarding.")
    db.alert("warn", "risk",
             "Geographic concentration: CA + FL exceed 35% of aggregate UPB.")
    db.alert("info", "valuation",
             "Monthly MSR mark refreshed across 3 portfolios; aggregate value +1.4% MoM.")
    db.alert("critical", "risk",
             "Coastal Jumbo book duration is short — MSR value falls sharply if rates rally 100bps.")


def _seed_audit():
    seeds = [
        ("Admin", "portfolio.import", "portfolio", 1, "allowed", "Imported Sunbelt Conventional tape (7 loans)."),
        ("Portfolio Manager", "valuation.run", "portfolio", 1, "allowed", "Ran base-case MSR valuation."),
        ("Seller/Transferor", "crx.create", "crx", 1, "allowed", "Created CRX-EXE-2601."),
        ("Seller/Transferor", "crx.bid", "crx", 1, "allowed", "Ran competitive SRP auction (8 servicers)."),
        ("Read-Only/Investor", "crx.award", "crx", 1, "denied", "Attempted award without permission."),
        ("Seller/Transferor", "crx.award", "crx", 1, "allowed", "Awarded auction to winning servicer."),
    ]
    for role, action, entity, eid, outcome, detail in seeds:
        db.audit(role, action, entity, eid, outcome, detail)


if __name__ == "__main__":
    build()
