"""Mock Freddie Mac Cash-Released XChange (CRX) bidding engine.

>>> SIMULATOR — NOT A REAL FREDDIE MAC INTEGRATION. <<<

Freddie Mac's Cash-Released XChange lets a seller deliver a loan to Freddie for
cash *and* simultaneously auction the servicing to a pool of approved
transferee servicers. The highest servicing-released premium (SRP) wins; the
seller keeps the sale reps & warranties while the winning servicer assumes the
servicing (a "bifurcation").

This module fabricates a *plausible* competitive auction: each simulated
servicer prices an SRP (in bps of UPB) off the pool's characteristics — credit,
note-rate incentive, escrow, delinquency and each servicer's own appetite — with
deterministic per-contract jitter so results are stable across runs. There is no
network call and no real pricing model; treat every number as illustrative.
"""
from __future__ import annotations

import hashlib
from statistics import mean

import db

# Per-servicer character: (base SRP bps, credit appetite, rate appetite).
# base_srp   — starting servicing-released premium in bps of UPB
# credit_beta— extra bps per 10 FICO points above 720
# rate_beta  — extra bps per 25bps of note rate above 6.0% (fee multiple upside)
SERVICER_PROFILE = {
    "Rocket Mortgage": (118, 1.4, 3.0),
    "Freedom Mortgage": (104, 0.8, 4.2),   # aggressive on higher-rate paper
    "Newrez": (110, 1.1, 3.4),
    "Chase": (122, 1.8, 2.2),              # premium buyer, credit-selective
    "Mr. Cooper": (112, 1.2, 3.0),
    "PennyMac": (108, 1.0, 3.6),
    "Lakeview": (106, 0.9, 3.2),
    "Carrington": (98, 0.6, 4.6),          # buys scratch-and-dent / higher DQ
}


def _jitter(seed_text: str) -> float:
    """Deterministic pseudo-random in [-1, 1] from a text seed."""
    h = hashlib.sha256(seed_text.encode()).hexdigest()
    return (int(h[:8], 16) / 0xFFFFFFFF) * 2 - 1


def pool_stats(loans: list[dict]) -> dict:
    if not loans:
        return {"upb": 0, "wac": 0, "fico": 0, "ltv": 0, "dq_pct": 0, "escrow_pct": 0, "n": 0}
    upb = sum(l["upb"] for l in loans)
    dq = sum(1 for l in loans if l["delinquency_status"] != "Current")
    esc = sum(1 for l in loans if l["escrow"])
    return {
        "upb": upb,
        "wac": mean(l["note_rate"] for l in loans),
        "fico": mean(l["fico"] for l in loans),
        "ltv": mean(l["ltv"] for l in loans),
        "dq_pct": dq / len(loans) * 100,
        "escrow_pct": esc / len(loans) * 100,
        "n": len(loans),
    }


def price_servicer(servicer: str, stats: dict, contract_key: str) -> dict:
    base, credit_beta, rate_beta = SERVICER_PROFILE[servicer]
    srp = base
    # Credit: reward FICO above 720.
    srp += credit_beta * (stats["fico"] - 720) / 10.0
    # Rate incentive: higher WAC => richer fee strip => higher SRP.
    srp += rate_beta * (stats["wac"] * 100 - 6.0) / 0.25
    # LTV haircut above 80.
    srp -= max(0.0, stats["ltv"] - 80) * 0.4
    # Delinquency haircut (most buyers dislike DQ; Carrington less so).
    dq_pen = 0.7 if servicer != "Carrington" else 0.25
    srp -= stats["dq_pct"] * dq_pen
    # Escrow adds float income.
    srp += stats["escrow_pct"] * 0.03
    # Deterministic per-contract, per-servicer jitter (±6 bps).
    srp += _jitter(contract_key + servicer) * 6.0
    srp = max(20.0, srp)

    # Asset price (the loan sale to Freddie): par plus a rate-driven premium.
    asset_price = 100.0 + (stats["wac"] * 100 - 6.0) * 1.1 - max(0.0, stats["ltv"] - 80) * 0.05
    asset_price = max(97.0, min(105.5, asset_price))

    srp_dollars = stats["upb"] * srp / 10000.0
    all_in = asset_price + srp / 100.0   # SRP bps expressed as % points of UPB
    return {
        "servicer": servicer,
        "srp_bps": round(srp, 1),
        "asset_price": round(asset_price, 3),
        "all_in_price": round(all_in, 3),
        "srp_dollars": round(srp_dollars, 2),
    }


def run_auction(contract_id: int) -> list[dict]:
    """Generate the full bid book for a contract, mark the winner, persist it."""
    contract = db.crx_contract(contract_id)
    loans = db.crx_loans(contract_id)
    stats = pool_stats(loans)
    excluded = {s.strip() for s in (contract.get("excluded") or "").split(",") if s.strip()}
    key = f"CRX-{contract_id}-{stats['n']}-{int(stats['upb'])}"

    bids = []
    for servicer in db.SERVICER_POOL:
        b = price_servicer(servicer, stats, key)
        b["excluded"] = 1 if servicer in excluded else 0
        b["won"] = 0
        bids.append(b)

    # Highest SRP among non-excluded wins.
    eligible = [b for b in bids if not b["excluded"]]
    if eligible:
        winner = max(eligible, key=lambda b: b["srp_bps"])
        winner["won"] = 1
        winner["note"] = "Cover bid" if len(eligible) > 1 else "Sole bid"

    bids.sort(key=lambda b: (b["excluded"], -b["srp_bps"]))
    db.replace_crx_bids(contract_id, bids)
    db.set_crx_status(contract_id, "Bidding")
    return db.crx_bids(contract_id)


def net_funding(contract_id: int) -> dict | None:
    """All-in net funding for the awarded bid: asset proceeds + SRP - fees."""
    contract = db.crx_contract(contract_id)
    bid = db.one("SELECT * FROM crx_bids WHERE id=?", (contract.get("awarded_bid_id") or 0,))
    if not bid:
        return None
    upb = contract["upb"]
    asset_proceeds = upb * bid["asset_price"] / 100.0
    srp_proceeds = bid["srp_dollars"]
    # Illustrative Freddie delivery / transfer fees.
    delivery_fee = upb * 0.0004          # 4 bps
    transfer_fee = 350.0 * contract["loan_count"]
    net = asset_proceeds + srp_proceeds - delivery_fee - transfer_fee
    return {
        "servicer": bid["servicer"],
        "upb": upb,
        "asset_price": bid["asset_price"],
        "asset_proceeds": asset_proceeds,
        "srp_bps": bid["srp_bps"],
        "srp_proceeds": srp_proceeds,
        "delivery_fee": delivery_fee,
        "transfer_fee": transfer_fee,
        "net_funding": net,
    }


# --- Imaged / Final document checklist (references Freddie Exhibit 28A) ------

# The document set a seller images and delivers on a servicing transfer. Exhibit
# 28A is Freddie Mac's Transfer of Servicing form / delivery instructions.
DOC_CHECKLIST = [
    ("Mortgage Note (endorsed)", "Exhibit 28A"),
    ("Recorded Security Instrument", "Exhibit 28A"),
    ("Assignment of Mortgage / MERS transfer", "Exhibit 28A"),
    ("Title Policy", "Exhibit 28A"),
    ("Escrow Analysis & Balances", "Exhibit 28A"),
    ("Payment History / Servicing File", "Exhibit 28A"),
    ("Goodbye / Hello Letters (RESPA §6)", "Exhibit 28A"),
    ("Bifurcation Agreement (reps retained)", "Exhibit 28A"),
    ("MERS MIN Confirmation", "Exhibit 28A"),
    ("Freddie Mac Funding & Delivery Detail", "Exhibit 28A"),
]

BIFURCATION_NOTE = (
    "Bifurcated execution: the <strong>seller retains</strong> all selling "
    "representations & warranties on the underlying loans, while the "
    "<strong>winning transferee servicer assumes servicing</strong> "
    "responsibilities and the servicing reps from the transfer date. "
    "Cash is released concurrently through Freddie Mac's Cash-Released XChange."
)
