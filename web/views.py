"""Center-pane page renderers for FastMSR."""
from __future__ import annotations

import json

from fasthtml.common import (
    Div, H1, H2, H3, H4, P, Span, A, Table, Thead, Tbody, Tr, Th, Td,
    Ul, Li, Strong, Em, NotStr, Form, Input, Button, Textarea, Select, Option,
    Label, Br,
)

import db
import crx
import valuation as val
from web.layout import title, kpi, pill, money, money0, pct


# ---------- inline SVG charts (no external libs) ----------------------------

def line_chart(points, labels, *, w=520, h=150, color="#F59E0B", fmt=money):
    if not points:
        return NotStr("<div style='color:var(--text-mute);font-size:12px'>No data.</div>")
    pad = 30
    lo, hi = min(points), max(points)
    if hi == lo:
        hi += 1
    n = len(points)
    def x(i): return pad + i * (w - 2 * pad) / max(n - 1, 1)
    def y(v): return h - pad - (v - lo) / (hi - lo) * (h - 2 * pad)
    pts = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in enumerate(points))
    dots = "".join(f"<circle cx='{x(i):.1f}' cy='{y(v):.1f}' r='2.6' fill='{color}'/>"
                   for i, v in enumerate(points))
    xlabels = "".join(
        f"<text x='{x(i):.1f}' y='{h-8}' fill='#94A3B8' font-size='9' text-anchor='middle'>{lab}</text>"
        for i, lab in enumerate(labels))
    area = f"{pad},{h-pad} " + pts + f" {x(n-1):.1f},{h-pad}"
    svg = f"""<svg viewBox='0 0 {w} {h}' width='100%' preserveAspectRatio='xMidYMid meet'>
      <polygon points='{area}' fill='{color}' opacity='0.08'/>
      <polyline points='{pts}' fill='none' stroke='{color}' stroke-width='2'/>
      {dots}{xlabels}
      <text x='{pad}' y='14' fill='#94A3B8' font-size='9'>{fmt(hi)}</text>
      <text x='{pad}' y='{h-pad+2}' fill='#94A3B8' font-size='9'>{fmt(lo)}</text>
    </svg>"""
    return NotStr(f"<div class='chart-frame'>{svg}</div>")


def bar_chart(rows_, *, w=520, h=170, color="#F59E0B"):
    """rows_: list of (label, value). Horizontal bars."""
    if not rows_:
        return NotStr("<div style='color:var(--text-mute)'>No data.</div>")
    mx = max(v for _, v in rows_) or 1
    bars = []
    for lab, v in rows_:
        pw = max(2, v / mx * 100)
        bars.append(
            f"<div class='bar-row'><div style='color:var(--text-dim)'>{lab}</div>"
            f"<div><div class='strat-bar' style='width:{pw:.0f}%'></div></div>"
            f"<div class='v'>{v:.0f} bps</div></div>")
    return NotStr("".join(bars))


# ---------- dashboard -------------------------------------------------------

def _mtm_series():
    rows_ = db.rows("""SELECT as_of, SUM(msr_value) v FROM valuations
                       WHERE scope='portfolio' GROUP BY as_of ORDER BY as_of""")
    return [r["v"] for r in rows_], [r["as_of"][5:] for r in rows_]


def dashboard():
    k = db.dashboard_kpis()
    series, labels = _mtm_series()

    # SRP by servicer from the live CRX book
    bidrows = db.rows("""SELECT servicer, srp_bps FROM crx_bids
                         WHERE excluded=0 ORDER BY srp_bps DESC LIMIT 6""")
    srp_bars = bar_chart([(b["servicer"], b["srp_bps"]) for b in bidrows])

    # transfer status breakdown
    tstat = db.rows("SELECT status, COUNT(*) n, COALESCE(SUM(upb),0) upb FROM transfers GROUP BY status")
    tstat_tbl = Table(
        Thead(Tr(Th("Status"), Th("Count", cls="num"), Th("UPB", cls="num"))),
        Tbody(*[Tr(Td(pill(r["status"])), Td(r["n"], cls="num"),
                   Td(money(r["upb"]), cls="num")) for r in tstat]), cls="tbl")

    # geographic concentration (risk exposure)
    geo = db.rows("""SELECT borrower_state st, SUM(upb) upb FROM loans
                     GROUP BY borrower_state ORDER BY upb DESC LIMIT 6""")
    tot = db.scalar("SELECT SUM(upb) FROM loans") or 1
    geo_bars = NotStr("".join(
        f"<div class='bar-row'><div>{g['st']}</div>"
        f"<div><div class='strat-bar' style='width:{g['upb']/tot*100:.0f}%;"
        f"background:{'#F87171' if g['upb']/tot>0.18 else '#F59E0B'}'></div></div>"
        f"<div class='v'>{money(g['upb'])} · {g['upb']/tot*100:.0f}%</div></div>"
        for g in geo))

    alerts = db.alerts()[:6]
    feed = Ul(*[Li(
        Div(Span(a["kind"], cls="kind"), " ", pill(a["level"]), " ",
            Span(a["created"][5:16], cls="when")),
        Div(a["message"], style="margin-top:3px;color:var(--text-dim)"),
    ) for a in alerts], cls="timeline") if alerts else P("No alerts.", cls="sub")

    return (
        title("MSR Command Center",
              "Portfolio value, exchange activity, transfer status and risk — synthetic demo book."),
        Div(
            kpi("Aggregate UPB", money(k["total_upb"]), f"{k['loan_count']} loans across 3 portfolios"),
            kpi("MSR Fair Value", money(k["msr_total"]), f"{k['msr_bps']:.0f} bps of UPB", tone="ok"),
            kpi("Active Transfers", k["active_transfers"],
                f"{k['open_exceptions']} open exception(s)", tone="warn" if k["open_exceptions"] else ""),
            kpi("Open Alerts", k["open_alerts"], f"{k['delinquent']} delinquent loans",
                tone="bad" if k["open_alerts"] else ""),
            cls="kpi-grid"),
        Div(
            Div(Div(H3("MSR mark-to-market"), Span("6-month trend, aggregate", cls="hint"), cls="card-header"),
                line_chart(series, labels), cls="card"),
            Div(Div(H3("Live CRX bids"), Span("SRP by servicer (bps)", cls="hint"), cls="card-header"),
                srp_bars, cls="card"),
            cls="grid-2"),
        Div(
            Div(Div(H3("Servicing transfers"), cls="card-header"), tstat_tbl, cls="card"),
            Div(Div(H3("Geographic concentration"), Span("red = >18% of UPB", cls="hint"), cls="card-header"),
                geo_bars, cls="card"),
            cls="grid-2"),
        Div(Div(H3("Recent alerts"), A("View all →", href="/alerts", cls="hint"), cls="card-header"),
            feed, cls="card"),
    )


def alerts_view():
    alerts = db.alerts()
    body = Table(
        Thead(Tr(Th("Level"), Th("Type"), Th("Message"), Th("When"))),
        Tbody(*[Tr(Td(pill(a["level"])), Td(a["kind"]),
                   Td(a["message"], style="color:var(--text-dim)"),
                   Td(a["created"][:16], cls="mono")) for a in alerts]),
        cls="tbl") if alerts else P("No alerts.", cls="sub")
    return (
        title("Alerts", "Bid wins, transfer deadlines, valuation changes and risk triggers.",
              Form(Button("Mark all read", cls="btn sm"), method="post", action="/alerts/read")),
        Div(body, cls="card"),
    )


# ---------- portfolios ------------------------------------------------------

def portfolios_list():
    pfs = db.portfolios()
    rows_ = [Tr(
        Td(A(p["name"], href=f"/portfolios/{p['id']}", style="font-weight:600")),
        Td(p["investor"]), Td(pill(p["strategy"] or "Undecided", "accent")),
        Td(p["loan_count"], cls="num"), Td(money(p["upb"]), cls="num"),
        Td(pct(p["wac"]), cls="num"), Td(f"{p['avg_fico']:.0f}", cls="num"),
    ) for p in pfs]
    return (
        title("Portfolios", "Onboarded loan tapes. Click a portfolio to stratify, QC and value it."),
        Div(Table(
            Thead(Tr(Th("Portfolio"), Th("Investor"), Th("Strategy"),
                     Th("Loans", cls="num"), Th("UPB", cls="num"),
                     Th("WAC", cls="num"), Th("Avg FICO", cls="num"))),
            Tbody(*rows_)), cls="card"),
    )


_STATE_BUCKETS = None


def portfolio_detail(pid: int):
    p = db.portfolio(pid)
    if not p:
        return title("Not found", "No such portfolio.")
    loans = db.loans(pid)
    flags = db.qc_flags(pid)

    loan_rows = [Tr(
        Td(A(l["loan_number"], href=f"/loans/{l['id']}", cls="mono")),
        Td(l["borrower_state"]), Td(money(l["upb"]), cls="num"),
        Td(pct(l["note_rate"]), cls="num"), Td(f"{l['ltv']:.0f}", cls="num"),
        Td(l["fico"], cls="num"), Td(l["product_type"]),
        Td(pill(l["delinquency_status"], "current" if l["delinquency_status"] == "Current" else "bad")),
    ) for l in loans]

    # stratifications
    fico_strat = db.stratify(pid, "fico", [
        ("< 680", "{c} < 680"), ("680–719", "{c} BETWEEN 680 AND 719"),
        ("720–759", "{c} BETWEEN 720 AND 759"), ("760+", "{c} >= 760")])
    rate_strat = db.stratify(pid, "note_rate", [
        ("< 6.0%", "{c} < 0.06"), ("6.0–6.5%", "{c} >= 0.06 AND {c} < 0.065"),
        ("6.5–7.0%", "{c} >= 0.065 AND {c} < 0.07"), ("7.0%+", "{c} >= 0.07")])
    geo_strat = db.rows(
        "SELECT borrower_state label, COUNT(*) n, SUM(upb) upb, AVG(note_rate) wac "
        "FROM loans WHERE portfolio_id=? GROUP BY borrower_state ORDER BY upb DESC LIMIT 8", (pid,))

    def strat_card(heading, data, total_upb):
        return Div(Div(H3(heading), cls="card-header"),
                   NotStr("".join(
                       f"<div class='bar-row'><div>{d['label']}</div>"
                       f"<div><div class='strat-bar' style='width:{d['upb']/total_upb*100:.0f}%'></div></div>"
                       f"<div class='v'>{money(d['upb'])} · {d['n']}</div></div>"
                       for d in data)), cls="card")

    tot = p["upb"] or 1
    errs = sum(1 for f in flags if f["severity"] == "Error")
    warns = len(flags) - errs
    qc_card = Div(
        Div(H3("Data validation / QC"),
            Span(f"{errs} errors · {warns} warnings", cls="hint"), cls="card-header"),
        Table(Thead(Tr(Th("Loan"), Th("Rule"), Th("Severity"), Th("Message"))),
              Tbody(*[Tr(Td(f["loan_number"], cls="mono"), Td(f["rule"]),
                         Td(pill(f["severity"])), Td(f["message"], style="color:var(--text-dim)"))
                      for f in flags])) if flags else P("All loans passed eligibility checks.", cls="sub"),
        cls="card")

    return (
        title(p["name"],
              f"{p['seller']} · {p['investor']} · strategy: {p['strategy']}",
              A("Value this book →", href=f"/valuation?pid={pid}", cls="btn primary"),
              A("Import loans", href=f"/portfolios/{pid}/import", cls="btn")),
        Div(
            kpi("UPB", money(p["upb"]), f"{p['loan_count']} loans"),
            kpi("WAC", pct(p["wac"]), "weighted avg coupon"),
            kpi("Avg FICO", f"{p['avg_fico']:.0f}", f"avg LTV {p['avg_ltv']:.0f}%"),
            kpi("QC Flags", len(flags), f"{errs} blocking", tone="bad" if errs else "ok"),
            cls="kpi-grid"),
        Div(strat_card("FICO stratification", fico_strat, tot),
            strat_card("Note-rate cohorts", rate_strat, tot), cls="grid-2"),
        strat_card("Geographic distribution", geo_strat, tot),
        qc_card,
        Div(Div(H3(f"Loan tape ({len(loans)})"), cls="card-header"),
            Table(Thead(Tr(Th("Loan #"), Th("State"), Th("UPB", cls="num"), Th("Rate", cls="num"),
                           Th("LTV", cls="num"), Th("FICO", cls="num"), Th("Product"), Th("Status"))),
                  Tbody(*loan_rows)), cls="card"),
    )


def import_form(pid: int):
    p = db.portfolio(pid)
    return (
        title("Import loans", f"Append loans to {p['name']} from a CSV tape."),
        Div(
            P(NotStr("Paste CSV rows with header: "
                     "<code>loan_number,state,upb,note_rate,servicing_fee_rate,ltv,fico,product_type,"
                     "escrow,delinquency,investor,remaining_term</code>. "
                     "Rates as decimals (0.0625). Missing fields are defaulted; eligibility QC runs on import."),
              cls="sub", style="margin-bottom:14px"),
            Form(
                Textarea(
                    "loan_number,state,upb,note_rate,servicing_fee_rate,ltv,fico,product_type,escrow,"
                    "delinquency,investor,remaining_term\n"
                    "PCS-NEW001,CA,325000,0.0675,0.0025,78,742,Fixed 30,1,Current,Freddie Mac,352\n"
                    "PCS-NEW002,TX,198500,0.0725,0.0025,88,701,Home Possible,1,Current,Freddie Mac,356",
                    name="csv", rows=9, style="width:100%;font-family:'JetBrains Mono',monospace;font-size:12px"),
                Div(Button("Import tape", cls="btn primary", type="submit"),
                    A("Cancel", href=f"/portfolios/{pid}", cls="btn ghost"),
                    style="display:flex;gap:10px;margin-top:12px"),
                method="post", action=f"/portfolios/{pid}/import"),
            cls="card"),
    )


def loan_detail(lid: int):
    l = db.loan(lid)
    if not l:
        return title("Not found", "No such loan.")
    a = val.Assumptions()
    r = val.value_loan(l["upb"], l["note_rate"], l["servicing_fee_rate"],
                       l["remaining_term"] or 360, a, keep_schedule=True)
    flags = db.rows("SELECT * FROM qc_flags WHERE loan_id=?", (lid,))

    sched = Table(
        Thead(Tr(Th("Mo", cls="num"), Th("Begin bal", cls="num"), Th("Sched prin", cls="num"),
                 Th("Prepay", cls="num"), Th("Fee inc", cls="num"), Th("Net", cls="num"),
                 Th("PV", cls="num"), Th("End bal", cls="num"))),
        Tbody(*[Tr(Td(s["month"], cls="num"), Td(money0(s["begin_bal"]), cls="num"),
                   Td(money0(s["sched_prin"]), cls="num"), Td(money0(s["prepay"]), cls="num"),
                   Td(money0(s["fee_income"]), cls="num"), Td(money0(s["net"]), cls="num"),
                   Td(money0(s["pv"]), cls="num"), Td(money0(s["end_bal"]), cls="num"))
                for s in r.schedule]), cls="tbl")

    return (
        title(f"Loan {l['loan_number']}",
              f"{l['portfolio_name']} · {l['borrower_state']} · {l['product_type']}"),
        Div(
            kpi("MSR value", money(r.msr_value), f"{r.msr_multiple:.2f}x annual fee", tone="ok"),
            kpi("UPB", money(l["upb"]), f"orig {money(l['orig_balance'])}"),
            kpi("Note rate", pct(l["note_rate"]), f"servicing fee {l['servicing_fee_rate']*10000:.0f} bps"),
            kpi("WAL", f"{r.wal_years:.1f}y", f"{l['remaining_term']} mo remaining"),
            cls="kpi-grid"),
        Div(
            Div(Div(H3("Loan attributes"), cls="card-header"),
                Div(*[Div(Span(k, cls="k"), Span(v, cls="v")) for k, v in [
                    ("Loan number", l["loan_number"]), ("State", l["borrower_state"]),
                    ("UPB", money0(l["upb"])), ("Note rate", pct(l["note_rate"])),
                    ("LTV / FICO / DTI", f"{l['ltv']:.0f}% · {l['fico']} · {l['dti']:.0f}%"),
                    ("Product", l["product_type"]),
                    ("Escrow", "Yes" if l["escrow"] else "Waived"),
                    ("Delinquency", l["delinquency_status"]),
                    ("Investor", l["investor"]), ("MERS MIN", l["mers_min"]),
                ]], cls="kv"), cls="card"),
            Div(Div(H3("Eligibility flags"), cls="card-header"),
                (Ul(*[Li(pill(f["severity"]), " ", Strong(f["rule"]), NotStr(" — " + f["message"]),
                         style="margin-bottom:8px;list-style:none") for f in flags], style="padding-left:0")
                 if flags else P("No QC flags — loan is delivery-eligible.", cls="sub")), cls="card"),
            cls="grid-2"),
        Div(Div(H3("Servicing cash-flow projection"),
                Span("base case — annual after year 1", cls="hint"), cls="card-header"),
            sched, cls="card"),
    )


# ---------- valuation & analytics -------------------------------------------

def _assumptions_from(cpr, dr, dc, sc):
    return val.Assumptions(cpr=cpr, default_rate=dr, discount_rate=dc, servicing_cost=sc)


def valuation_view(pid=None, cpr=0.08, default_rate=0.005, discount_rate=0.10, servicing_cost=85.0):
    pfs = db.portfolios()
    if not pfs:
        return title("Valuation", "No portfolios to value.")
    pid = int(pid) if pid else pfs[0]["id"]
    p = db.portfolio(pid)
    loans = db.loans(pid)
    a = _assumptions_from(float(cpr), float(default_rate), float(discount_rate), float(servicing_cost))
    res = val.value_portfolio(loans, a)
    scen = val.scenarios(loans, a)
    rm = val.risk_metrics(loans, a)

    # retain vs release using best live SRP bid on any contract for this pf
    best_srp = db.scalar("""SELECT MAX(b.srp_bps) FROM crx_bids b
                            JOIN crx_contracts c ON c.id=b.contract_id
                            WHERE c.portfolio_id=? AND b.excluded=0""", (pid,))
    rr = val.retain_vs_release(res.msr_bps, best_srp)

    hist = db.valuation_history("portfolio", pid)
    hseries = [h["msr_value"] for h in hist]
    hlabels = [h["as_of"][5:] for h in hist]

    picker = Form(
        Div(Label("Portfolio"),
            Select(*[Option(pf["name"], value=pf["id"], selected=(pf["id"] == pid)) for pf in pfs],
                   name="pid"), cls="field"),
        Div(Label("Prepayment CPR"), Input(name="cpr", value=f"{a.cpr}", type="number", step="0.005"),
            Span("annual", cls="unit"), cls="field"),
        Div(Label("Default rate"), Input(name="default_rate", value=f"{a.default_rate}", type="number", step="0.001"),
            Span("annual CDR", cls="unit"), cls="field"),
        Div(Label("Discount rate"), Input(name="discount_rate", value=f"{a.discount_rate}", type="number", step="0.005"),
            Span("annual", cls="unit"), cls="field"),
        Div(Label("Servicing cost"), Input(name="servicing_cost", value=f"{a.servicing_cost}", type="number", step="5"),
            Span("$/loan/yr", cls="unit"), cls="field"),
        Div(Button("Recompute", cls="btn primary", type="submit"), style="display:flex;align-items:flex-end",
            cls="field"),
        method="get", action="/valuation", cls="form-grid",
        style="align-items:end;background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:16px;margin-bottom:16px")

    scen_tbl = Table(
        Thead(Tr(Th("Rate shock"), Th("CPR", cls="num"), Th("Discount", cls="num"),
                 Th("MSR value", cls="num"), Th("bps", cls="num"), Th("Δ value", cls="num"), Th("Δ %", cls="num"))),
        Tbody(*[Tr(
            Td(Strong(f"{s['shock']:+d} bps") if s["shock"] else Strong("Base")),
            Td(pct(s["cpr"], 1), cls="num"), Td(pct(s["discount_rate"], 1), cls="num"),
            Td(money(s["msr_value"]), cls="num"), Td(f"{s['msr_bps']:.0f}", cls="num"),
            Td(money(s["delta"]), cls="num",
               style=f"color:{'var(--ok)' if s['delta']>=0 else 'var(--bad)'}"),
            Td(f"{s['delta_pct']:+.1f}%", cls="num",
               style=f"color:{'var(--ok)' if s['delta']>=0 else 'var(--bad)'}"),
        ) for s in scen]), cls="tbl")

    return (
        title("MSR Valuation & Analytics",
              "Loan-level DCF aggregated to portfolio. Adjust assumptions and re-run scenarios.",
              A("Export CSV", href=f"/valuation/export?pid={pid}&cpr={a.cpr}&default_rate={a.default_rate}"
                f"&discount_rate={a.discount_rate}&servicing_cost={a.servicing_cost}", cls="btn")),
        picker,
        Div(
            kpi("MSR fair value", money(res.msr_value), f"{p['name']}", tone="ok"),
            kpi("Value in bps", f"{res.msr_bps:.0f} bps", f"{res.msr_multiple:.2f}x annual fee"),
            kpi("Eff. duration", f"{rm['duration']:.1f}", "±25bps discount bump"),
            kpi("Convexity", f"{rm['convexity']:.0f}", f"WAL {res.wal_years:.1f}y"),
            cls="kpi-grid"),
        Div(
            Div(Div(H3("Interest-rate scenario analysis"),
                    Span("MSR is a negative-duration asset — it gains when rates rise", cls="hint"),
                    cls="card-header"), scen_tbl, cls="card"),
            cls="grid-1"),
        Div(
            Div(Div(H3("Retain vs. release signal"), cls="card-header"),
                Div(Span(rr["signal"], cls=f"signal {rr['signal']}"),
                    style="margin-bottom:12px"),
                P(NotStr(rr["rationale"]), cls="sub"),
                Div(Span("Intrinsic MSR", cls="k"), Span(f"{res.msr_bps:.0f} bps", cls="v"),
                    Span("Best live SRP", cls="k"),
                    Span(f"{best_srp:.0f} bps" if best_srp else "—", cls="v"),
                    Span("Prepay sensitivity (+5 CPR)", cls="k"),
                    Span(money(rm["prepay_sens_5cpr"]), cls="v"),
                    cls="kv", style="margin-top:12px"), cls="card"),
            Div(Div(H3("Mark-to-market history"), Span("month-end MSR value", cls="hint"), cls="card-header"),
                line_chart(hseries, hlabels),
                P(f"Latest recorded mark: {money(hseries[-1])} on {hist[-1]['as_of']}" if hist else "",
                  cls="sub", style="margin-top:8px"), cls="card"),
            cls="grid-2"),
        Div(
            NotStr("<strong>Model:</strong> monthly DCF of the servicing-fee strip net of a "
                   "per-loan cost, amortised by the note's schedule plus a CPR prepayment and a "
                   "small default rate, discounted at the chosen rate. Multiple = MSR ÷ annual "
                   "servicing fee. Duration &amp; convexity from a ±25bps discount-rate bump."),
            cls="callout"),
    )


def valuation_export(pid, cpr, default_rate, discount_rate, servicing_cost):
    loans = db.loans(int(pid))
    a = _assumptions_from(float(cpr), float(default_rate), float(discount_rate), float(servicing_cost))
    lines = ["loan_number,state,upb,note_rate,servicing_fee_rate,remaining_term,msr_value,msr_multiple,wal_years"]
    for l in loans:
        r = val.value_loan(l["upb"], l["note_rate"], l["servicing_fee_rate"], l["remaining_term"] or 360, a)
        lines.append(f"{l['loan_number']},{l['borrower_state']},{l['upb']:.2f},{l['note_rate']},"
                     f"{l['servicing_fee_rate']},{l['remaining_term']},{r.msr_value:.2f},"
                     f"{r.msr_multiple:.4f},{r.wal_years:.2f}")
    port = val.value_portfolio(loans, a)
    lines.append(f"TOTAL,,{port.upb:.2f},,,,{port.msr_value:.2f},{port.msr_multiple:.4f},{port.wal_years:.2f}")
    return "\n".join(lines)


# ---------- CRX exchange (MOCK) ---------------------------------------------

SIM_BANNER = Div(NotStr(
    "<strong>⚠ SIMULATOR.</strong> This is a mock of Freddie Mac's Cash-Released XChange. "
    "There is no live Freddie Mac / Loan Selling Advisor connection — servicer bids are "
    "generated by a local pricing model for demonstration only."), cls="callout sim")


def crx_list():
    cts = db.crx_contracts()
    rows_ = [Tr(
        Td(A(c["name"], href=f"/crx/{c['id']}", style="font-weight:600")),
        Td(c["portfolio_name"] or "—"), Td(pill(c["status"])),
        Td(c["loan_count"], cls="num"), Td(money(c["upb"]), cls="num"),
    ) for c in cts]
    return (
        SIM_BANNER,
        title("CRX Exchange", "Cash-Released XChange executions — select loans, auction the servicing.",
              A("New execution", href="/crx/new", cls="btn primary")),
        Div(Table(
            Thead(Tr(Th("Execution"), Th("Portfolio"), Th("Status"),
                     Th("Loans", cls="num"), Th("UPB", cls="num"))),
            Tbody(*rows_)) if cts else P("No CRX executions yet.", cls="sub"), cls="card"),
    )


def crx_new_form():
    pfs = db.portfolios()
    return (
        SIM_BANNER,
        title("New CRX execution", "Create a Cash-Released contract and select the delivery pool."),
        Form(
            Div(Label("Execution name"),
                Input(name="name", value="CRX-EXE-2602 · New Delivery", required=True), cls="field"),
            Div(Label("Portfolio"),
                Select(*[Option(f"{p['name']} ({p['loan_count']} loans, {money(p['upb'])})",
                                value=p["id"]) for p in pfs], name="pid",
                       hx_get="/crx/loan-options", hx_target="#loan-select", hx_swap="innerHTML"),
                cls="field"),
            Div(Label("Loans (defaults to the first eligible five)"),
                Div(_loan_options(pfs[0]["id"]) if pfs else None, id="loan-select"), cls="field"),
            Div(Button("Create execution", cls="btn primary", type="submit"),
                A("Cancel", href="/crx", cls="btn ghost"), style="display:flex;gap:10px;margin-top:8px"),
            method="post", action="/crx/new"),
    )


def _loan_options(pid):
    loans = db.loans(int(pid))
    return Div(*[Div(
        Input(type="checkbox", name="loan_ids", value=l["id"], checked=(i < 5),
              id=f"ln{l['id']}", style="margin-right:8px"),
        Label(f"{l['loan_number']} · {money(l['upb'])} · {pct(l['note_rate'])} · "
              f"FICO {l['fico']} · {l['delinquency_status']}",
              **{"for": f"ln{l['id']}"}, style="font-weight:400;text-transform:none;letter-spacing:0"),
        style="display:flex;align-items:center;padding:4px 0") for i, l in enumerate(loans)],
        style="max-height:280px;overflow-y:auto;border:1px solid var(--border);border-radius:8px;padding:8px 12px")


def crx_detail(cid: int):
    c = db.crx_contract(cid)
    if not c:
        return title("Not found", "No such execution.")
    loans = db.crx_loans(cid)
    bids = db.crx_bids(cid)
    stats = crx.pool_stats(loans)

    loan_tbl = Table(
        Thead(Tr(Th("Loan"), Th("State"), Th("UPB", cls="num"), Th("Rate", cls="num"),
                 Th("FICO", cls="num"), Th("Status"))),
        Tbody(*[Tr(Td(A(l["loan_number"], href=f"/loans/{l['id']}", cls="mono")), Td(l["borrower_state"]),
                   Td(money(l["upb"]), cls="num"), Td(pct(l["note_rate"]), cls="num"),
                   Td(l["fico"], cls="num"),
                   Td(pill(l["delinquency_status"], "current" if l["delinquency_status"] == "Current" else "bad")))
                for l in loans]), cls="tbl")

    excluded = {s.strip() for s in (c.get("excluded") or "").split(",") if s.strip()}
    bid_rows = []
    for b in bids:
        winner = b["won"]
        bid_rows.append(Tr(
            Td(Strong(b["servicer"]) if winner else b["servicer"],
               (" 🏆" if winner else "")),
            Td(f"{b['srp_bps']:.0f} bps", cls="num", style="font-weight:600"),
            Td(money(b["srp_dollars"]), cls="num"),
            Td(f"{b['asset_price']:.3f}", cls="num"),
            Td(f"{b['all_in_price']:.3f}", cls="num"),
            Td(pill("Excluded", "bad") if b["excluded"] else (pill("Won", "won") if winner else pill("Cover", "info"))),
            Td(Form(Button("Award", cls="btn sm primary", type="submit"),
                    Input(type="hidden", name="bid_id", value=b["id"]),
                    method="post", action=f"/crx/{cid}/award") if not b["excluded"] and not winner else
               (Span("Awarded", cls="pill won") if winner else Span("—"))),
            style="opacity:.5" if b["excluded"] else ""))
    bid_tbl = Table(
        Thead(Tr(Th("Servicer"), Th("SRP", cls="num"), Th("SRP $", cls="num"),
                 Th("Asset px", cls="num"), Th("All-in", cls="num"), Th("Result"), Th(""))),
        Tbody(*bid_rows), cls="tbl") if bids else P("No bids yet — run the auction.", cls="sub")

    # servicer exclusion toggles
    excl_form = Form(
        Div(*[Label(Input(type="checkbox", name="excluded", value=s, checked=(s in excluded),
                          style="margin-right:6px"), s,
                    style="font-weight:400;text-transform:none;letter-spacing:0;margin-right:14px;display:inline-flex;align-items:center")
              for s in db.SERVICER_POOL], style="display:flex;flex-wrap:wrap;gap:8px 4px;margin-bottom:10px"),
        Div(Button("Run competitive auction", cls="btn primary", type="submit"),
            style="display:flex;gap:10px"),
        method="post", action=f"/crx/{cid}/run")

    # net funding + bifurcation if awarded
    extras = []
    nf = crx.net_funding(cid) if c["status"] in ("Awarded", "Funded") else None
    if nf:
        extras.append(Div(
            Div(H3("Automated net funding"), Span(f"winner: {nf['servicer']}", cls="hint"), cls="card-header"),
            Div(*[Div(Span(k, cls="k"), Span(v, cls="v")) for k, v in [
                ("Pool UPB", money0(nf["upb"])),
                ("Asset price", f"{nf['asset_price']:.3f}% → {money0(nf['asset_proceeds'])}"),
                ("SRP", f"{nf['srp_bps']:.0f} bps → {money0(nf['srp_proceeds'])}"),
                ("Delivery fee (4 bps)", "-" + money0(nf["delivery_fee"])),
                ("Transfer fee", "-" + money0(nf["transfer_fee"])),
            ]], cls="kv"),
            Div(Span("Net funding", cls="k", style="font-weight:600"),
                Span(money0(nf["net_funding"]), cls="v", style="font-weight:700;color:var(--ok);font-size:18px"),
                cls="kv", style="margin-top:10px;padding-top:10px;border-top:1px solid var(--border)"),
            Div(NotStr(crx.BIFURCATION_NOTE), cls="callout", style="margin-top:14px;margin-bottom:0"),
            cls="card"))
        # document checklist
        docs = "".join(
            f"<div class='check'><span class='nm'>{name}</span>"
            f"<span class='pill accent'>{exhibit}</span>"
            f"<span class='pill {'ok' if i%3 else 'warn'}'>{'Final' if i%3 else 'Imaged'}</span></div>"
            for i, (name, exhibit) in enumerate(crx.DOC_CHECKLIST))
        extras.append(Div(Div(H3("Imaged / final document checklist"),
                              Span("references Freddie Exhibit 28A", cls="hint"), cls="card-header"),
                          NotStr(docs), cls="card"))
        extras.append(Form(Button("Initiate concurrent servicing transfer →", cls="btn primary", type="submit"),
                           method="post", action=f"/crx/{cid}/transfer",
                           style="margin-bottom:16px"))

    return (
        SIM_BANNER,
        title(c["name"], f"{c['portfolio_name']} · seller {c['seller']}",
              pill(c["status"], "accent")),
        Div(
            kpi("Pool UPB", money(stats["upb"]), f"{stats['n']} loans"),
            kpi("WAC", pct(stats["wac"]) if stats["n"] else "—", "weighted coupon"),
            kpi("Avg FICO", f"{stats['fico']:.0f}" if stats["n"] else "—", f"LTV {stats['ltv']:.0f}%"),
            kpi("Delinquent", f"{stats['dq_pct']:.0f}%", "of pool by count",
                tone="bad" if stats["dq_pct"] > 5 else "ok"),
            cls="kpi-grid"),
        Div(Div(H3("Servicer pool & exclusions"),
                Span("uncheck to exclude a servicer from the auction", cls="hint"), cls="card-header"),
            excl_form, cls="card"),
        Div(Div(H3("Competitive SRP bid book"),
                Span("highest servicing-released premium wins", cls="hint"), cls="card-header"),
            bid_tbl, cls="card"),
        *extras,
        Div(Div(H3(f"Loans in execution ({len(loans)})"), cls="card-header"), loan_tbl, cls="card"),
    )


# ---------- servicing transfers ---------------------------------------------

def transfers_list():
    trs = db.transfers()
    rows_ = [Tr(
        Td(A(f"T-{t['id']} · {t['portfolio_name']}", href=f"/transfers/{t['id']}", style="font-weight:600")),
        Td(t["kind"]), Td(t["transferee"]), Td(pill(t["status"])),
        Td(t["loan_count"], cls="num"), Td(money(t["upb"]), cls="num"),
        Td(t["effective_date"], cls="mono"),
    ) for t in trs]
    return (
        title("Servicing Transfers", "Concurrent (CRX) and standalone transfers — status, docs, exceptions."),
        Div(Table(
            Thead(Tr(Th("Transfer"), Th("Type"), Th("Transferee"), Th("Status"),
                     Th("Loans", cls="num"), Th("UPB", cls="num"), Th("Effective"))),
            Tbody(*rows_)) if trs else P("No transfers.", cls="sub"), cls="card"),
    )


def transfer_detail(tid: int):
    t = db.transfer(tid)
    if not t:
        return title("Not found", "No such transfer.")
    docs = db.transfer_docs(tid)
    events = db.transfer_events(tid)
    excs = db.transfer_exceptions(tid)

    flow = [s for s in db.TRANSFER_STATUSES if s != "Exception"]
    cur_i = flow.index(t["status"]) if t["status"] in flow else 0
    steps = NotStr("<div style='display:flex;gap:6px;flex-wrap:wrap;margin-bottom:6px'>" + "".join(
        f"<span class='pill {'ok' if i < cur_i else ('accent' if i==cur_i else '')}'>{s}</span>"
        for i, s in enumerate(flow)) + "</div>")

    doc_rows = [Tr(
        Td(d["name"]), Td(pill(d["exhibit"], "accent")),
        Td(pill(d["status"])), Td(f"v{d['version']}", cls="mono"),
        Td(Form(Select(*[Option(s, value=s, selected=(s == d["status"]))
                         for s in ["Missing", "Imaged", "Final"]], name="status",
                       onchange="this.form.submit()", cls="btn sm"),
                Input(type="hidden", name="doc_id", value=d["id"]),
                method="post", action=f"/transfers/{tid}/doc")),
    ) for d in docs]

    exc_body = Table(
        Thead(Tr(Th("Kind"), Th("Message"), Th("Status"), Th(""))),
        Tbody(*[Tr(Td(pill(e["kind"], "bad")), Td(e["message"], style="color:var(--text-dim)"),
                   Td(pill(e["status"])),
                   Td(Form(Button("Resolve", cls="btn sm", type="submit"),
                           Input(type="hidden", name="exc_id", value=e["id"]),
                           method="post", action=f"/transfers/{tid}/resolve")
                      if e["status"] == "Open" else Span("—")))
                for e in excs]), cls="tbl") if excs else P("No open exceptions.", cls="sub")

    timeline = Ul(*[Li(
        Div(Span(e["kind"], cls="kind"), " ", Span(e["created"][5:16], cls="when")),
        Div(NotStr(e["body"] or ""), style="margin-top:2px;color:var(--text-dim)")) for e in events],
        cls="timeline")

    finalized = sum(1 for d in docs if d["status"] == "Final")
    return (
        title(f"Transfer T-{tid}", f"{t['kind']} · {t['transferor']} → {t['transferee']}",
              Form(Button("Advance stage →", cls="btn primary", type="submit"),
                   method="post", action=f"/transfers/{tid}/advance")
              if t["status"] != "Completed" else pill("Completed", "ok")),
        Div(
            kpi("Status", t["status"], f"{t['loan_count']} loans · {money(t['upb'])}",
                tone="bad" if excs and any(e["status"] == "Open" for e in excs) else ""),
            kpi("Documents", f"{finalized}/{len(docs)}", "finalized", tone="ok" if finalized == len(docs) else "warn"),
            kpi("Exceptions", sum(1 for e in excs if e["status"] == "Open"), "open",
                tone="bad" if any(e["status"] == "Open" for e in excs) else "ok"),
            kpi("MERS batch", t["mers_batch"] or "—", "registration ref"),
            cls="kpi-grid"),
        Div(Div(H3("Workflow"), cls="card-header"), steps,
            P(NotStr("Concurrent transfers move in lock-step with the CRX funding; standalone "
                     "transfers are bulk servicing sales. Borrower notices honor the CFPB 15-day rule."),
              cls="sub", style="margin-top:8px"), cls="card"),
        Div(Div(Div(H3("Document checklist & versioning"),
                    Span("packaged per Exhibit 28A", cls="hint"), cls="card-header"),
                Table(Thead(Tr(Th("Document"), Th("Exhibit"), Th("Status"), Th("Ver"), Th("Set"))),
                      Tbody(*doc_rows)), cls="card"),
            Div(Div(H3("Exceptions"), cls="card-header"), exc_body, cls="card"),
            cls="grid-2"),
        Div(Div(H3("Notifications & event log"), cls="card-header"), timeline, cls="card"),
    )


# ---------- compliance & risk -----------------------------------------------

def compliance_view():
    items = db.compliance_items()
    by_cat = {}
    for it in items:
        by_cat.setdefault(it["category"], []).append(it)

    cat_cards = []
    for cat, its in by_cat.items():
        rows_ = [Tr(
            Td(it["item"]), Td(pill(it["reference"], "accent")),
            Td(it["owner_role"], cls="mono"), Td(pill(it["status"])),
            Td(Form(Select(*[Option(s, value=s, selected=(s == it["status"]))
                             for s in ["Open", "Satisfied", "N/A"]], name="status",
                           onchange="this.form.submit()", cls="btn sm"),
                    Input(type="hidden", name="item_id", value=it["id"]),
                    method="post", action="/compliance/item")),
        ) for it in its]
        cat_cards.append(Div(Div(H3(cat), cls="card-header"),
                             Table(Thead(Tr(Th("Requirement"), Th("Reference"), Th("Owner"),
                                            Th("Status"), Th("Set"))),
                                   Tbody(*rows_)), cls="card"))

    # risk flags computed live
    tot = db.scalar("SELECT SUM(upb) FROM loans") or 1
    geo = db.rows("SELECT borrower_state st, SUM(upb) upb FROM loans GROUP BY borrower_state ORDER BY upb DESC")
    top2 = sum(g["upb"] for g in geo[:2]) / tot * 100
    fast_pct = (db.scalar("SELECT SUM(upb) FROM loans WHERE note_rate >= 0.07") or 0) / tot * 100
    dq_pct = (db.scalar("SELECT SUM(upb) FROM loans WHERE delinquency_status!='Current'") or 0) / tot * 100
    risk_rows = [
        ("Geographic concentration", f"Top-2 states = {top2:.0f}% of UPB",
         "bad" if top2 > 35 else "ok",
         "Diversify or buy geographic hedge if this breaches the 35% internal limit."),
        ("Prepayment / rate incentive", f"{fast_pct:.0f}% of UPB at ≥7.0% note rate",
         "warn" if fast_pct > 25 else "ok",
         "High-rate paper prepays fast if rates rally — shortens MSR duration."),
        ("Credit / delinquency", f"{dq_pct:.0f}% of UPB delinquent",
         "bad" if dq_pct > 5 else "ok",
         "Delinquent loans are CRX-ineligible and raise advance obligations."),
    ]
    risk_card = Div(Div(H3("Risk flags"), Span("computed on the live book", cls="hint"), cls="card-header"),
                    Table(Thead(Tr(Th("Risk"), Th("Reading"), Th("Flag"), Th("Note"))),
                          Tbody(*[Tr(Td(Strong(nm)), Td(rd), Td(pill(fl.upper(), fl)),
                                     Td(note, style="color:var(--text-mute);font-size:12px"))
                                  for nm, rd, fl, note in risk_rows])), cls="card")

    # simple hedging suggestion
    a = val.Assumptions()
    all_loans = db.rows("SELECT * FROM loans")
    rm = val.risk_metrics(all_loans, a)
    dv01 = abs(rm["base_value"] * rm["duration"] * 0.0001)
    hedge = Div(Div(H3("Hedging suggestion"), cls="card-header"),
                P(NotStr(f"Aggregate MSR effective duration is <strong>{rm['duration']:.1f}</strong> "
                         f"(negative-duration asset). Approx DV01 ≈ <strong>{money0(dv01)}</strong> per bp. "
                         "To neutralize rate risk, <strong>pay-fixed on swaps / short Treasury futures</strong> "
                         "is the wrong direction — instead buy <strong>receiver swaptions or long "
                         "TBA/Treasury duration</strong> to offset the MSR's gain-when-rates-rise profile, "
                         "sizing the hedge notional to match DV01."), cls="sub"), cls="card")

    return (
        title("Compliance & Risk", "Regulatory checklist, live risk flags and a hedging read."),
        Div(risk_card, hedge, cls="grid-2"),
        *cat_cards,
    )


def audit_view():
    rows_ = db.audit_rows(200)
    body = Table(
        Thead(Tr(Th("When"), Th("Role"), Th("Action"), Th("Entity"), Th("Outcome"), Th("Detail"))),
        Tbody(*[Tr(Td(a["created"][:19], cls="mono"), Td(a["role"]),
                   Td(Span(a["action"], cls="mono")), Td(f"{a['entity']}#{a['entity_id']}" if a["entity"] else "—"),
                   Td(pill(a["outcome"])), Td(a["detail"], style="color:var(--text-dim)"))
                for a in rows_]), cls="tbl")
    return (
        title("Audit Trail", "Every permissioned action is logged with the acting role and outcome (RBAC)."),
        Div(body, cls="card"),
    )


def guide_view():
    return (
        title("User Guide", "How to drive FastMSR."),
        Div(NotStr("""
<div class='card'><h3>Roles &amp; RBAC</h3><p>Use the <strong>Acting as</strong> switch in the top bar to
change role (Seller/Transferor, Transferee/Buyer, Portfolio Manager, Compliance Officer, Read-Only/Investor,
Admin). Write actions are permission-checked and <em>every attempt</em> — allowed or denied — is written to
the Audit Trail. Try running an auction or awarding a bid as <em>Read-Only/Investor</em> to see a denial.</p></div>
<div class='card'><h3>Portfolios</h3><p>Three seeded loan tapes. Open one to see FICO / rate / geographic
stratifications, data-validation QC flags against eligibility rules, and the full loan tape. Import more loans
from a CSV paste.</p></div>
<div class='card'><h3>Valuation &amp; Analytics</h3><p>A real monthly DCF of the servicing-fee strip. Adjust
CPR, default rate, discount rate and servicing cost, then recompute. Scenario table shocks rates ±100/±200bps;
duration &amp; convexity come from a ±25bps discount bump. A retain-vs-release signal compares intrinsic MSR
value against the best live CRX bid. Export loan-level values to CSV.</p></div>
<div class='card'><h3>CRX Exchange <span class='pill bad'>Simulator</span></h3><p>A mock of Freddie Mac's
Cash-Released XChange. Create an execution, pick loans, exclude servicers, and run a competitive SRP auction
against a simulated pool (Rocket, Freedom, Newrez, Chase, …). Highest SRP wins; award it to see automated net
funding, the bifurcation note and the Exhibit 28A document checklist. <strong>No real Freddie Mac connection.</strong></p></div>
<div class='card'><h3>Servicing Transfers</h3><p>Concurrent (CRX) or standalone. Track the workflow, package and
version the document checklist, resolve data-discrepancy exceptions, and watch borrower/investor notifications
in the event log (CFPB 15-day rule).</p></div>
<div class='card'><h3>Compliance &amp; Risk / Audit</h3><p>Freddie Guide and CFPB checklist items, live risk
flags (concentration, prepayment, credit), a hedging suggestion, and the full audit trail.</p></div>
""")),
    )
