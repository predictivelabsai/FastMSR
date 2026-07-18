"""FastMSR data layer — a thin wrapper over SQLite.

A compact relational model for a Mortgage Servicing Rights (MSR) management
system: loan portfolios, loan-level tapes, MSR valuations & mark-to-market
history, a (mock) Freddie Mac Cash-Released XChange bidding book, servicing
transfers with document checklists, compliance/audit logging and alerts.

Everything is synthetic; see ``seed.py``. The database path resolves from
``FASTMSR_DB`` (env) or defaults to ``fastmsr.sqlite`` beside this file.
"""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = os.getenv("FASTMSR_DB") or str(Path(__file__).parent / "fastmsr.sqlite")

# --- domain vocabularies (kept here so seed + UI + engines agree) -----------

ROLES = [
    "Admin",
    "Seller/Transferor",
    "Transferee/Buyer",
    "Portfolio Manager",
    "Compliance Officer",
    "Read-Only/Investor",
]

# Coarse action → allowed-roles map. Enforced on write endpoints; every attempt
# (allowed or denied) is written to the audit log.
PERMISSIONS = {
    "portfolio.import": {"Admin", "Seller/Transferor", "Portfolio Manager"},
    "valuation.run": {"Admin", "Seller/Transferor", "Portfolio Manager"},
    "crx.create": {"Admin", "Seller/Transferor", "Portfolio Manager"},
    "crx.bid": {"Admin", "Seller/Transferor", "Portfolio Manager"},
    "crx.award": {"Admin", "Seller/Transferor"},
    "transfer.advance": {"Admin", "Seller/Transferor", "Transferee/Buyer"},
    "transfer.doc": {"Admin", "Seller/Transferor", "Transferee/Buyer"},
    "compliance.signoff": {"Admin", "Compliance Officer"},
}

PRODUCT_TYPES = ["Fixed 30", "Fixed 15", "ARM 5/6", "ARM 7/6", "Home Possible"]
DELINQUENCY = ["Current", "30 DPD", "60 DPD", "90+ DPD"]
INVESTORS = ["Freddie Mac", "Fannie Mae", "Ginnie Mae", "Portfolio"]

CRX_STATUSES = ["Draft", "Bidding", "Awarded", "Funded", "Cancelled"]
TRANSFER_STATUSES = [
    "Initiated",
    "Docs Pending",
    "Data Validation",
    "Notification",     # CFPB / Freddie borrower & investor notices
    "Boarding",
    "Completed",
    "Exception",
]
TRANSFER_TYPES = ["Concurrent (CRX)", "Standalone"]

# Simulated transferee servicer pool for the mock CRX bidding engine.
SERVICER_POOL = [
    "Rocket Mortgage", "Freedom Mortgage", "Newrez", "Chase",
    "Mr. Cooper", "PennyMac", "Lakeview", "Carrington",
]


# --- connection -------------------------------------------------------------

def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


@contextmanager
def cursor():
    conn = connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def db_exists() -> bool:
    p = Path(DB_PATH)
    return p.exists() and p.stat().st_size > 0


def rows(sql: str, params: tuple = ()) -> list[dict]:
    with cursor() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def one(sql: str, params: tuple = ()) -> dict | None:
    with cursor() as conn:
        r = conn.execute(sql, params).fetchone()
        return dict(r) if r else None


def scalar(sql: str, params: tuple = ()):
    with cursor() as conn:
        r = conn.execute(sql, params).fetchone()
        return r[0] if r else None


# --- schema -----------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS portfolios (
    id            INTEGER PRIMARY KEY,
    name          TEXT NOT NULL,
    seller        TEXT,
    investor      TEXT,
    strategy      TEXT,            -- 'Retain' | 'Release' | 'Undecided'
    notes         TEXT,
    created       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS loans (
    id                  INTEGER PRIMARY KEY,
    portfolio_id        INTEGER REFERENCES portfolios(id),
    loan_number         TEXT NOT NULL,
    borrower_state      TEXT,
    upb                 REAL NOT NULL,          -- unpaid principal balance
    orig_balance        REAL,
    note_rate           REAL NOT NULL,          -- annual, decimal (0.065)
    servicing_fee_rate  REAL NOT NULL,          -- annual, decimal (0.0025)
    ltv                 REAL,
    fico                INTEGER,
    dti                 REAL,
    product_type        TEXT,
    escrow              INTEGER DEFAULT 1,       -- boolean
    delinquency_status  TEXT DEFAULT 'Current',
    investor            TEXT,
    remaining_term      INTEGER,                 -- months
    age_months          INTEGER,
    mers_min            TEXT,                    -- MERS Mortgage Identification Number
    created             TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS qc_flags (
    id            INTEGER PRIMARY KEY,
    loan_id       INTEGER REFERENCES loans(id),
    rule          TEXT NOT NULL,
    severity      TEXT NOT NULL,      -- 'Error' | 'Warning'
    message       TEXT,
    created       TEXT NOT NULL
);

-- MSR valuation runs (loan- or portfolio-level). Also serves as the
-- mark-to-market history when as_of dates differ.
CREATE TABLE IF NOT EXISTS valuations (
    id            INTEGER PRIMARY KEY,
    scope         TEXT NOT NULL,      -- 'portfolio' | 'loan'
    ref_id        INTEGER NOT NULL,
    as_of         TEXT NOT NULL,
    msr_value     REAL NOT NULL,
    msr_multiple  REAL,
    upb           REAL,
    assumptions   TEXT NOT NULL,      -- JSON: cpr, default_rate, discount_rate, servicing_cost
    created       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS crx_contracts (
    id            INTEGER PRIMARY KEY,
    name          TEXT NOT NULL,
    seller        TEXT,
    portfolio_id  INTEGER REFERENCES portfolios(id),
    status        TEXT NOT NULL DEFAULT 'Draft',
    excluded      TEXT DEFAULT '',    -- comma-list of excluded servicer names
    awarded_bid_id INTEGER,
    created       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS crx_contract_loans (
    contract_id   INTEGER REFERENCES crx_contracts(id),
    loan_id       INTEGER REFERENCES loans(id),
    PRIMARY KEY (contract_id, loan_id)
);

CREATE TABLE IF NOT EXISTS crx_bids (
    id             INTEGER PRIMARY KEY,
    contract_id    INTEGER REFERENCES crx_contracts(id),
    servicer       TEXT NOT NULL,
    srp_bps        REAL NOT NULL,      -- servicing-released premium, bps of UPB
    asset_price    REAL NOT NULL,      -- % of UPB (par ~ 100)
    all_in_price   REAL NOT NULL,      -- asset price + SRP, % of UPB
    srp_dollars    REAL,
    excluded       INTEGER DEFAULT 0,
    won            INTEGER DEFAULT 0,
    note           TEXT,
    created        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS transfers (
    id             INTEGER PRIMARY KEY,
    contract_id    INTEGER REFERENCES crx_contracts(id),
    portfolio_id   INTEGER REFERENCES portfolios(id),
    transferor     TEXT,
    transferee     TEXT,
    kind           TEXT NOT NULL,      -- Concurrent (CRX) | Standalone
    status         TEXT NOT NULL DEFAULT 'Initiated',
    loan_count     INTEGER DEFAULT 0,
    upb            REAL DEFAULT 0,
    effective_date TEXT,
    mers_batch     TEXT,
    created        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS transfer_docs (
    id             INTEGER PRIMARY KEY,
    transfer_id    INTEGER REFERENCES transfers(id),
    name           TEXT NOT NULL,
    exhibit        TEXT,              -- e.g. 'Exhibit 28A'
    status         TEXT NOT NULL,     -- 'Missing' | 'Imaged' | 'Final'
    version        INTEGER DEFAULT 1,
    updated        TEXT
);

CREATE TABLE IF NOT EXISTS transfer_events (
    id             INTEGER PRIMARY KEY,
    transfer_id    INTEGER REFERENCES transfers(id),
    kind           TEXT NOT NULL,     -- status | note | notification | exception | doc
    body           TEXT,
    created        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS exceptions (
    id             INTEGER PRIMARY KEY,
    transfer_id    INTEGER REFERENCES transfers(id),
    kind           TEXT NOT NULL,     -- 'Missing Doc' | 'Data Discrepancy'
    message        TEXT,
    status         TEXT NOT NULL DEFAULT 'Open',   -- Open | Resolved
    created        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS compliance_items (
    id             INTEGER PRIMARY KEY,
    category       TEXT NOT NULL,     -- 'Freddie Guide' | 'CFPB' | 'Internal'
    item           TEXT NOT NULL,
    reference      TEXT,
    status         TEXT NOT NULL DEFAULT 'Open',   -- Open | Satisfied | N/A
    owner_role     TEXT,
    updated        TEXT
);

CREATE TABLE IF NOT EXISTS alerts (
    id             INTEGER PRIMARY KEY,
    level          TEXT NOT NULL,     -- info | warn | critical
    kind           TEXT NOT NULL,     -- bid | transfer | valuation | risk
    message        TEXT NOT NULL,
    is_read        INTEGER DEFAULT 0,
    created        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
    id             INTEGER PRIMARY KEY,
    role           TEXT,
    action         TEXT NOT NULL,
    entity         TEXT,
    entity_id      INTEGER,
    outcome        TEXT NOT NULL,     -- allowed | denied
    detail         TEXT,
    created        TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_loans_pf     ON loans(portfolio_id);
CREATE INDEX IF NOT EXISTS idx_qc_loan      ON qc_flags(loan_id);
CREATE INDEX IF NOT EXISTS idx_val_ref      ON valuations(scope, ref_id);
CREATE INDEX IF NOT EXISTS idx_bids_ct      ON crx_bids(contract_id);
CREATE INDEX IF NOT EXISTS idx_evt_tr       ON transfer_events(transfer_id);
CREATE INDEX IF NOT EXISTS idx_docs_tr      ON transfer_docs(transfer_id);
"""


def init_schema() -> None:
    with cursor() as conn:
        conn.executescript(SCHEMA)


# --- audit + RBAC -----------------------------------------------------------

def can(role: str, action: str) -> bool:
    allowed = PERMISSIONS.get(action)
    return allowed is None or role in allowed


def audit(role: str, action: str, entity: str = "", entity_id: int = 0,
          outcome: str = "allowed", detail: str = "") -> None:
    with cursor() as conn:
        conn.execute(
            "INSERT INTO audit_log(role,action,entity,entity_id,outcome,detail,created) "
            "VALUES (?,?,?,?,?,?,datetime('now'))",
            (role, action, entity, entity_id, outcome, detail))


def guard(role: str, action: str, entity: str = "", entity_id: int = 0,
          detail: str = "") -> bool:
    """Check a permission and audit the attempt. Returns True if allowed."""
    ok = can(role, action)
    audit(role, action, entity, entity_id, "allowed" if ok else "denied", detail)
    return ok


def alert(level: str, kind: str, message: str) -> None:
    with cursor() as conn:
        conn.execute(
            "INSERT INTO alerts(level,kind,message,is_read,created) "
            "VALUES (?,?,?,0,datetime('now'))", (level, kind, message))


# --- portfolio + loan reads -------------------------------------------------

def portfolios() -> list[dict]:
    return rows("""
        SELECT p.*, COUNT(l.id) AS loan_count,
               COALESCE(SUM(l.upb),0) AS upb,
               COALESCE(AVG(l.note_rate),0) AS wac,
               COALESCE(AVG(l.fico),0) AS avg_fico
        FROM portfolios p LEFT JOIN loans l ON l.portfolio_id = p.id
        GROUP BY p.id ORDER BY upb DESC""")


def portfolio(pid: int) -> dict | None:
    return one("""
        SELECT p.*, COUNT(l.id) AS loan_count,
               COALESCE(SUM(l.upb),0) AS upb,
               COALESCE(AVG(l.note_rate),0) AS wac,
               COALESCE(AVG(l.fico),0) AS avg_fico,
               COALESCE(AVG(l.ltv),0) AS avg_ltv
        FROM portfolios p LEFT JOIN loans l ON l.portfolio_id = p.id
        WHERE p.id = ? GROUP BY p.id""", (pid,))


def loans(pid: int) -> list[dict]:
    return rows("SELECT * FROM loans WHERE portfolio_id=? ORDER BY upb DESC", (pid,))


def loan(lid: int) -> dict | None:
    return one("""SELECT l.*, p.name AS portfolio_name
                  FROM loans l LEFT JOIN portfolios p ON p.id=l.portfolio_id
                  WHERE l.id=?""", (lid,))


def loan_ids(pid: int) -> list[int]:
    return [r["id"] for r in rows("SELECT id FROM loans WHERE portfolio_id=?", (pid,))]


def qc_flags(pid: int) -> list[dict]:
    return rows("""SELECT q.*, l.loan_number FROM qc_flags q
                   JOIN loans l ON l.id=q.loan_id
                   WHERE l.portfolio_id=? ORDER BY q.severity, q.id""", (pid,))


def stratify(pid: int, column: str, buckets) -> list[dict]:
    """Return count/UPB/WAC strata for a portfolio by a bucketed column.

    ``buckets`` is a list of (label, sql_predicate) with ``{c}`` placeholder
    for the column name.
    """
    out = []
    for label, pred in buckets:
        r = one(
            f"""SELECT COUNT(*) n, COALESCE(SUM(upb),0) upb,
                       COALESCE(AVG(note_rate),0) wac, COALESCE(AVG(fico),0) fico
                FROM loans WHERE portfolio_id=? AND {pred.format(c=column)}""",
            (pid,))
        if r and r["n"]:
            out.append({"label": label, **r})
    return out


# --- valuation history ------------------------------------------------------

def latest_valuation(scope: str, ref_id: int) -> dict | None:
    return one("""SELECT * FROM valuations WHERE scope=? AND ref_id=?
                  ORDER BY as_of DESC, id DESC LIMIT 1""", (scope, ref_id))


def valuation_history(scope: str, ref_id: int) -> list[dict]:
    return rows("""SELECT * FROM valuations WHERE scope=? AND ref_id=?
                   ORDER BY as_of""", (scope, ref_id))


def save_valuation(scope, ref_id, as_of, msr_value, msr_multiple, upb, assumptions):
    with cursor() as conn:
        conn.execute(
            "INSERT INTO valuations(scope,ref_id,as_of,msr_value,msr_multiple,upb,assumptions,created)"
            " VALUES (?,?,?,?,?,?,?,datetime('now'))",
            (scope, ref_id, as_of, msr_value, msr_multiple, upb, json.dumps(assumptions)))


# --- CRX reads --------------------------------------------------------------

def crx_contracts() -> list[dict]:
    return rows("""
        SELECT c.*, p.name AS portfolio_name,
               (SELECT COUNT(*) FROM crx_contract_loans cl WHERE cl.contract_id=c.id) AS loan_count,
               (SELECT COALESCE(SUM(l.upb),0) FROM crx_contract_loans cl
                  JOIN loans l ON l.id=cl.loan_id WHERE cl.contract_id=c.id) AS upb
        FROM crx_contracts c LEFT JOIN portfolios p ON p.id=c.portfolio_id
        ORDER BY c.id DESC""")


def crx_contract(cid: int) -> dict | None:
    return one("""
        SELECT c.*, p.name AS portfolio_name,
               (SELECT COUNT(*) FROM crx_contract_loans cl WHERE cl.contract_id=c.id) AS loan_count,
               (SELECT COALESCE(SUM(l.upb),0) FROM crx_contract_loans cl
                  JOIN loans l ON l.id=cl.loan_id WHERE cl.contract_id=c.id) AS upb,
               (SELECT COALESCE(AVG(l.note_rate),0) FROM crx_contract_loans cl
                  JOIN loans l ON l.id=cl.loan_id WHERE cl.contract_id=c.id) AS wac,
               (SELECT COALESCE(AVG(l.fico),0) FROM crx_contract_loans cl
                  JOIN loans l ON l.id=cl.loan_id WHERE cl.contract_id=c.id) AS fico,
               (SELECT COALESCE(AVG(l.ltv),0) FROM crx_contract_loans cl
                  JOIN loans l ON l.id=cl.loan_id WHERE cl.contract_id=c.id) AS ltv
        FROM crx_contracts c LEFT JOIN portfolios p ON p.id=c.portfolio_id
        WHERE c.id=?""", (cid,))


def crx_loans(cid: int) -> list[dict]:
    return rows("""SELECT l.* FROM crx_contract_loans cl JOIN loans l ON l.id=cl.loan_id
                   WHERE cl.contract_id=? ORDER BY l.upb DESC""", (cid,))


def crx_bids(cid: int) -> list[dict]:
    return rows("SELECT * FROM crx_bids WHERE contract_id=? ORDER BY srp_bps DESC", (cid,))


def create_crx_contract(name, seller, portfolio_id, loan_ids_) -> int:
    with cursor() as conn:
        conn.execute(
            "INSERT INTO crx_contracts(name,seller,portfolio_id,status,created)"
            " VALUES (?,?,?, 'Draft', datetime('now'))", (name, seller, portfolio_id))
        cid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        for lid in loan_ids_:
            conn.execute("INSERT OR IGNORE INTO crx_contract_loans(contract_id,loan_id) VALUES (?,?)",
                         (cid, lid))
    return cid


def set_crx_status(cid: int, status: str):
    with cursor() as conn:
        conn.execute("UPDATE crx_contracts SET status=? WHERE id=?", (status, cid))


def replace_crx_bids(cid: int, bids: list[dict]):
    with cursor() as conn:
        conn.execute("DELETE FROM crx_bids WHERE contract_id=?", (cid,))
        for b in bids:
            conn.execute(
                "INSERT INTO crx_bids(contract_id,servicer,srp_bps,asset_price,all_in_price,"
                "srp_dollars,excluded,won,note,created) VALUES (?,?,?,?,?,?,?,?,?,datetime('now'))",
                (cid, b["servicer"], b["srp_bps"], b["asset_price"], b["all_in_price"],
                 b["srp_dollars"], b["excluded"], b["won"], b.get("note", "")))


def award_bid(cid: int, bid_id: int):
    with cursor() as conn:
        conn.execute("UPDATE crx_bids SET won=0 WHERE contract_id=?", (cid,))
        conn.execute("UPDATE crx_bids SET won=1 WHERE id=?", (bid_id,))
        conn.execute("UPDATE crx_contracts SET status='Awarded', awarded_bid_id=? WHERE id=?",
                     (bid_id, cid))


# --- transfers --------------------------------------------------------------

def transfers() -> list[dict]:
    return rows("""SELECT t.*, p.name AS portfolio_name FROM transfers t
                   LEFT JOIN portfolios p ON p.id=t.portfolio_id ORDER BY t.id DESC""")


def transfer(tid: int) -> dict | None:
    return one("""SELECT t.*, p.name AS portfolio_name FROM transfers t
                  LEFT JOIN portfolios p ON p.id=t.portfolio_id WHERE t.id=?""", (tid,))


def transfer_docs(tid: int) -> list[dict]:
    return rows("SELECT * FROM transfer_docs WHERE transfer_id=? ORDER BY id", (tid,))


def transfer_events(tid: int) -> list[dict]:
    return rows("SELECT * FROM transfer_events WHERE transfer_id=? ORDER BY created DESC, id DESC",
                (tid,))


def transfer_exceptions(tid: int) -> list[dict]:
    return rows("SELECT * FROM exceptions WHERE transfer_id=? ORDER BY status, id", (tid,))


def transfer_event(tid: int, kind: str, body: str):
    with cursor() as conn:
        conn.execute(
            "INSERT INTO transfer_events(transfer_id,kind,body,created) VALUES (?,?,?,datetime('now'))",
            (tid, kind, body))


def advance_transfer(tid: int) -> str | None:
    t = transfer(tid)
    if not t:
        return None
    flow = [s for s in TRANSFER_STATUSES if s != "Exception"]
    try:
        i = flow.index(t["status"])
    except ValueError:
        i = 0
    if i >= len(flow) - 1:
        return t["status"]
    nxt = flow[i + 1]
    with cursor() as conn:
        conn.execute("UPDATE transfers SET status=? WHERE id=?", (nxt, tid))
    transfer_event(tid, "status", f"Advanced to <strong>{nxt}</strong>.")
    if nxt == "Notification":
        transfer_event(tid, "notification",
                       "Borrower goodbye/hello letters queued (CFPB 15-day rule); "
                       "investor notice sent to transferee.")
    return nxt


def set_doc_status(doc_id: int, status: str):
    with cursor() as conn:
        row = conn.execute("SELECT transfer_id, name, version FROM transfer_docs WHERE id=?",
                           (doc_id,)).fetchone()
        conn.execute("UPDATE transfer_docs SET status=?, version=version+1, updated=datetime('now') WHERE id=?",
                     (status, doc_id))
    if row:
        transfer_event(row[0], "doc", f"Document <strong>{row[1]}</strong> marked {status} (v{row[2]+1}).")


# --- compliance + audit + alerts reads --------------------------------------

def compliance_items() -> list[dict]:
    return rows("SELECT * FROM compliance_items ORDER BY category, id")


def set_compliance_status(item_id: int, status: str):
    with cursor() as conn:
        conn.execute("UPDATE compliance_items SET status=?, updated=datetime('now') WHERE id=?",
                     (status, item_id))


def audit_rows(limit: int = 200) -> list[dict]:
    return rows("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,))


def alerts(unread_only: bool = False) -> list[dict]:
    if unread_only:
        return rows("SELECT * FROM alerts WHERE is_read=0 ORDER BY id DESC")
    return rows("SELECT * FROM alerts ORDER BY id DESC LIMIT 100")


def mark_alerts_read():
    with cursor() as conn:
        conn.execute("UPDATE alerts SET is_read=1")


def dashboard_kpis() -> dict:
    total_upb = scalar("SELECT COALESCE(SUM(upb),0) FROM loans") or 0
    loan_count = scalar("SELECT COUNT(*) FROM loans") or 0
    # Latest portfolio MSR values summed.
    msr_total = 0.0
    for p in portfolios():
        v = latest_valuation("portfolio", p["id"])
        if v:
            msr_total += v["msr_value"]
    active_transfers = scalar(
        "SELECT COUNT(*) FROM transfers WHERE status NOT IN ('Completed')") or 0
    open_alerts = scalar("SELECT COUNT(*) FROM alerts WHERE is_read=0") or 0
    open_exceptions = scalar("SELECT COUNT(*) FROM exceptions WHERE status='Open'") or 0
    delinquent = scalar(
        "SELECT COUNT(*) FROM loans WHERE delinquency_status != 'Current'") or 0
    return {
        "total_upb": total_upb,
        "loan_count": loan_count,
        "msr_total": msr_total,
        "msr_bps": (msr_total / total_upb * 10000) if total_upb else 0,
        "active_transfers": active_transfers,
        "open_alerts": open_alerts,
        "open_exceptions": open_exceptions,
        "delinquent": delinquent,
    }
