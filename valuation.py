"""MSR valuation & analytics engine.

A real (if deliberately simple) monthly discounted-cash-flow model for the
value of a mortgage servicing right. The servicer earns a servicing fee strip
off the outstanding balance each month, pays a per-loan servicing cost, and the
net strip is discounted back. Prepayments (CPR) and defaults amortise the
balance faster than the note's own schedule, which is what makes MSR valuation
interesting: faster prepay => the fee strip dies sooner => lower MSR value.

Nothing here calls an external service; it is pure arithmetic so it runs
zero-config and is fully deterministic.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Assumptions:
    cpr: float = 0.08                 # annual conditional prepayment rate
    default_rate: float = 0.005       # annual conditional default rate
    discount_rate: float = 0.10       # annual discount rate
    servicing_cost: float = 85.0      # $ per loan per year (direct cost to service)
    ancillary: float = 25.0           # $ per loan per year (late fees, float, etc.)

    def as_dict(self) -> dict:
        return {
            "cpr": self.cpr,
            "default_rate": self.default_rate,
            "discount_rate": self.discount_rate,
            "servicing_cost": self.servicing_cost,
            "ancillary": self.ancillary,
        }


def psa_to_cpr(psa: float, age_months: int) -> float:
    """Convert a PSA speed to a single (seasoned) CPR for reference."""
    ramp = min(age_months, 30)
    return (psa / 100.0) * 0.06 * (ramp / 30.0)


def _payment(balance: float, monthly_rate: float, n: int) -> float:
    if n <= 0:
        return balance
    if monthly_rate <= 0:
        return balance / n
    return balance * monthly_rate / (1 - (1 + monthly_rate) ** (-n))


@dataclass
class LoanResult:
    msr_value: float
    msr_multiple: float          # MSR value / annual servicing fee $
    wal_years: float             # weighted-average life of the servicing cashflows
    schedule: list = field(default_factory=list)


def value_loan(upb: float, note_rate: float, servicing_fee_rate: float,
               remaining_term: int, a: Assumptions,
               keep_schedule: bool = False) -> LoanResult:
    """Loan-level MSR DCF. Returns value plus (optionally) the monthly schedule."""
    term = max(int(remaining_term or 0), 1)
    smm = 1 - (1 - a.cpr) ** (1 / 12)
    mdr = 1 - (1 - a.default_rate) ** (1 / 12)
    r_note = note_rate / 12.0
    r_disc = a.discount_rate / 12.0
    pay = _payment(upb, r_note, term)

    bal = upb
    pv = 0.0
    annual_fee0 = upb * servicing_fee_rate
    wal_num = 0.0
    fee_sum = 0.0
    schedule = []
    for m in range(1, term + 1):
        if bal <= 1.0:
            break
        interest = bal * r_note
        sched_prin = min(max(pay - interest, 0.0), bal)
        bal_after = bal - sched_prin
        prepay = bal_after * smm
        default_prin = bal_after * mdr
        fee_income = bal * servicing_fee_rate / 12.0 + a.ancillary / 12.0
        cost = a.servicing_cost / 12.0
        net = fee_income - cost
        df = 1.0 / ((1 + r_disc) ** m)
        pv += net * df
        fee_sum += fee_income
        wal_num += m * (sched_prin + prepay + default_prin)
        end_bal = max(bal_after - prepay - default_prin, 0.0)
        if keep_schedule and (m <= 12 or m % 12 == 0):
            schedule.append({
                "month": m,
                "begin_bal": bal,
                "sched_prin": sched_prin,
                "prepay": prepay,
                "fee_income": fee_income,
                "net": net,
                "pv": net * df,
                "end_bal": end_bal,
            })
        bal = end_bal

    multiple = pv / annual_fee0 if annual_fee0 else 0.0
    wal = (wal_num / upb / 12.0) if upb else 0.0
    return LoanResult(msr_value=pv, msr_multiple=multiple, wal_years=wal, schedule=schedule)


@dataclass
class PortfolioResult:
    msr_value: float
    msr_multiple: float
    upb: float
    msr_bps: float               # value as bps of UPB
    wal_years: float
    loan_count: int


def value_portfolio(loans: list[dict], a: Assumptions) -> PortfolioResult:
    total_val = 0.0
    total_upb = 0.0
    total_fee = 0.0
    wal_w = 0.0
    for ln in loans:
        upb = ln["upb"]
        r = value_loan(upb, ln["note_rate"], ln["servicing_fee_rate"],
                       ln.get("remaining_term") or 360, a)
        total_val += r.msr_value
        total_upb += upb
        total_fee += upb * ln["servicing_fee_rate"]
        wal_w += r.wal_years * upb
    mult = total_val / total_fee if total_fee else 0.0
    return PortfolioResult(
        msr_value=total_val,
        msr_multiple=mult,
        upb=total_upb,
        msr_bps=(total_val / total_upb * 10000) if total_upb else 0.0,
        wal_years=(wal_w / total_upb) if total_upb else 0.0,
        loan_count=len(loans),
    )


# --- scenario analysis ------------------------------------------------------

def shock_assumptions(a: Assumptions, bps: int) -> Assumptions:
    """Apply a parallel interest-rate shock.

    Falling rates (negative shock) speed prepayments up and pull discount
    rates down; rising rates slow prepays and lift discounts. MSR value is a
    negative-duration asset — it *gains* when rates rise.
    """
    # CPR moves ~ -20% per +100bps (loans prepay slower), floored/capped.
    cpr_mult = max(0.25, 1.0 - 0.20 * (bps / 100.0))
    new_cpr = min(0.60, max(0.02, a.cpr * cpr_mult))
    new_disc = max(0.03, a.discount_rate + 0.5 * bps / 10000.0)
    return Assumptions(cpr=new_cpr, default_rate=a.default_rate,
                       discount_rate=new_disc, servicing_cost=a.servicing_cost,
                       ancillary=a.ancillary)


SHOCKS = [-200, -100, 0, 100, 200]


def scenarios(loans: list[dict], base: Assumptions) -> list[dict]:
    out = []
    base_val = value_portfolio(loans, base).msr_value
    for bps in SHOCKS:
        a = base if bps == 0 else shock_assumptions(base, bps)
        r = value_portfolio(loans, a)
        out.append({
            "shock": bps,
            "cpr": a.cpr,
            "discount_rate": a.discount_rate,
            "msr_value": r.msr_value,
            "msr_bps": r.msr_bps,
            "delta": r.msr_value - base_val,
            "delta_pct": (r.msr_value - base_val) / base_val * 100 if base_val else 0.0,
        })
    return out


def risk_metrics(loans: list[dict], base: Assumptions) -> dict:
    """Effective duration & convexity from a ±25bps discount-rate bump, plus a
    prepayment-sensitivity read and a breakeven servicing-cost figure."""
    dy = 0.0025
    v0 = value_portfolio(loans, base).msr_value
    up = value_portfolio(loans, shock_assumptions(base, 25)).msr_value
    dn = value_portfolio(loans, shock_assumptions(base, -25)).msr_value
    duration = -(up - dn) / (2 * v0 * dy) if v0 else 0.0
    convexity = (up + dn - 2 * v0) / (v0 * dy * dy) if v0 else 0.0

    # Prepay sensitivity: value change for +5 CPR (absolute).
    a_fast = Assumptions(cpr=min(0.60, base.cpr + 0.05), default_rate=base.default_rate,
                         discount_rate=base.discount_rate, servicing_cost=base.servicing_cost,
                         ancillary=base.ancillary)
    v_fast = value_portfolio(loans, a_fast).msr_value
    prepay_sens = v_fast - v0

    return {
        "base_value": v0,
        "duration": duration,
        "convexity": convexity,
        "prepay_sens_5cpr": prepay_sens,
    }


def retain_vs_release(portfolio_msr_bps: float, best_srp_bps: float | None) -> dict:
    """Signal: hold the MSR (retain) or sell servicing-released.

    Compares the intrinsic MSR value (bps of UPB) against the best all-in SRP
    a buyer will pay. If a buyer pays materially above intrinsic, release.
    """
    if best_srp_bps is None:
        return {"signal": "Retain", "rationale":
                "No live CRX bid — hold and remit; re-price when the exchange opens."}
    edge = best_srp_bps - portfolio_msr_bps
    if edge > 15:
        sig, why = "Release", ("Best SRP exceeds intrinsic MSR by "
                               f"{edge:.0f} bps — sell servicing-released and book the premium.")
    elif edge < -15:
        sig, why = "Retain", ("Intrinsic MSR is "
                              f"{-edge:.0f} bps above the market SRP — retain and service.")
    else:
        sig, why = "Neutral", ("SRP and intrinsic value are within 15 bps — "
                               "decision driven by capital, hedging capacity and liquidity.")
    return {"signal": sig, "rationale": why, "edge_bps": edge}
