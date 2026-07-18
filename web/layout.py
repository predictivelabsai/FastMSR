"""FastMSR shell: top bar (brand, role switch), left nav, center work area.

Server-rendered FastHTML FT components, dark slate palette with an amber
accent, HTMX for in-page actions. No client-side framework.
"""
from __future__ import annotations

from fasthtml.common import (
    Div, H1, H2, H3, H4, P, Span, A, Button, Form, Input, Title, Link,
    Script, Style, NotStr, Select, Option, Label,
)

import db

# Dark slate + amber — matches the Procredio / Predictive Labs family palette.
LAYOUT_CSS = """
:root{
  --bg:#0F172A; --surface:#1E293B; --surface-2:#334155; --border:#334155; --border-2:#475569;
  --text:#F8FAFC; --text-dim:#CBD5E1; --text-mute:#94A3B8;
  --accent:#F59E0B; --accent-hover:#FBBF24; --accent-deep:#78350F; --accent-dim:#451A03;
  --ok:#34D399; --ok-dim:#064E3B; --warn:#FBBF24; --warn-dim:#713F12;
  --bad:#F87171; --bad-dim:#7F1D1D; --info:#60A5FA; --info-dim:#1E3A8A;
}
*{box-sizing:border-box;}
html,body{margin:0;padding:0;height:100%;background:var(--bg);color:var(--text);
  font-family:'Inter',ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;font-size:14px;}
a{color:var(--accent);text-decoration:none;} a:hover{color:var(--accent-hover);}
code{font-family:'JetBrains Mono',ui-monospace,monospace;font-size:12.5px;background:rgba(245,158,11,.1);
  color:var(--accent-hover);padding:1px 5px;border-radius:4px;}
h1,h2,h3,h4{color:var(--text);}

.app{display:grid;grid-template-columns:238px 1fr;grid-template-rows:54px 1fr;
  grid-template-areas:"top top" "left center";height:100vh;overflow:hidden;}

.topbar{grid-area:top;display:flex;align-items:center;justify-content:space-between;
  padding:0 22px;background:var(--surface);border-bottom:1px solid var(--border);}
.brand{font-weight:700;letter-spacing:.3px;display:flex;align-items:center;gap:9px;font-size:16px;}
.brand-dot{width:12px;height:12px;background:var(--accent);border-radius:3px;transform:rotate(45deg);display:inline-block;}
.env-pill{background:var(--accent-dim);color:var(--accent-hover);padding:3px 10px;border-radius:999px;
  font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.6px;border:1px solid var(--accent-deep);}
.topbar .actions{display:flex;gap:12px;align-items:center;}
.role-switch{display:flex;align-items:center;gap:7px;font-size:12px;color:var(--text-mute);}
.role-switch select{background:var(--surface-2);color:var(--text);border:1px solid var(--border-2);
  border-radius:8px;padding:5px 9px;font-size:12.5px;font-weight:600;}
.role-switch select:focus{outline:none;border-color:var(--accent);}

.left-pane{grid-area:left;background:var(--surface);border-right:1px solid var(--border);
  padding:12px 0;overflow-y:auto;}
.nav-section{margin-bottom:14px;}
.nav-section h4{margin:8px 18px 5px;font-size:10.5px;text-transform:uppercase;letter-spacing:.9px;
  color:var(--text-mute);font-weight:700;}
.nav-item{display:flex;align-items:center;gap:10px;padding:8px 18px;color:var(--text-dim);
  cursor:pointer;border-left:3px solid transparent;font-size:13.5px;}
.nav-item:hover{background:var(--surface-2);color:var(--text);}
.nav-item.active{background:linear-gradient(90deg,rgba(245,158,11,.14),transparent);
  color:var(--accent-hover);border-left-color:var(--accent);font-weight:600;}
.nav-icon{width:18px;display:inline-block;text-align:center;}
.nav-badge{margin-left:auto;background:var(--bad);color:#fff;font-size:10px;font-weight:700;
  border-radius:999px;padding:1px 7px;}

.center-pane{grid-area:center;overflow-y:auto;padding:22px 26px 60px;}
.page-title{display:flex;align-items:flex-start;justify-content:space-between;margin-bottom:18px;gap:16px;}
.page-title h1{margin:0;font-size:22px;font-weight:700;letter-spacing:-.02em;}
.page-title .sub{color:var(--text-mute);font-size:13px;margin-top:4px;max-width:70ch;}

.kpi-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:22px;}
.kpi{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:15px 17px;
  position:relative;overflow:hidden;}
.kpi .label{font-size:10.5px;text-transform:uppercase;letter-spacing:.7px;color:var(--text-mute);font-weight:600;}
.kpi .value{font-size:25px;font-weight:700;margin-top:5px;color:var(--text);font-variant-numeric:tabular-nums;}
.kpi .trend{font-size:12px;color:var(--text-mute);margin-top:3px;}
.kpi::after{content:'';position:absolute;top:0;right:0;bottom:0;width:4px;background:var(--accent);}
.kpi.ok::after{background:var(--ok);} .kpi.warn::after{background:var(--warn);} .kpi.bad::after{background:var(--bad);}

.card{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:17px 19px;margin-bottom:16px;}
.card-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:13px;gap:12px;}
.card-header h3{margin:0;font-size:15px;font-weight:700;}
.card-header .hint{font-size:11.5px;color:var(--text-mute);}
.grid-2{display:grid;grid-template-columns:1fr 1fr;gap:16px;}
.grid-3{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;}
@media(max-width:1100px){.kpi-grid{grid-template-columns:repeat(2,1fr);}.grid-2,.grid-3{grid-template-columns:1fr;}}

table.tbl{width:100%;border-collapse:collapse;font-size:12.5px;}
table.tbl th{text-align:left;padding:8px 10px;background:var(--surface-2);color:var(--text-dim);
  font-weight:600;border-bottom:1px solid var(--border);white-space:nowrap;font-size:11px;
  text-transform:uppercase;letter-spacing:.4px;}
table.tbl td{padding:8px 10px;border-bottom:1px solid var(--border);color:var(--text-dim);}
table.tbl tr:last-child td{border-bottom:0;}
table.tbl tr:hover td{background:rgba(148,163,184,.06);color:var(--text);}
.num{text-align:right;font-variant-numeric:tabular-nums;}
.mono{font-family:'JetBrains Mono',monospace;font-size:11.5px;}

.pill{display:inline-block;padding:2px 9px;border-radius:999px;font-size:10.5px;font-weight:600;
  background:var(--surface-2);color:var(--text-dim);white-space:nowrap;letter-spacing:.2px;}
.pill.ok,.pill.current,.pill.final,.pill.satisfied,.pill.completed,.pill.won,.pill.allowed{background:var(--ok-dim);color:var(--ok);}
.pill.warn,.pill.imaged,.pill.bidding,.pill.open,.pill.pending{background:var(--warn-dim);color:var(--warn);}
.pill.bad,.pill.missing,.pill.error,.pill.exception,.pill.denied,.pill.critical,.pill.cancelled{background:var(--bad-dim);color:var(--bad);}
.pill.info,.pill.draft,.pill.initiated{background:var(--info-dim);color:var(--info);}
.pill.accent{background:var(--accent-dim);color:var(--accent-hover);border:1px solid var(--accent-deep);}

.btn{padding:7px 13px;border-radius:8px;border:1px solid var(--border-2);background:var(--surface-2);
  color:var(--text);cursor:pointer;font-size:13px;font-weight:500;display:inline-flex;align-items:center;gap:6px;
  text-decoration:none;}
.btn:hover{border-color:var(--accent);color:var(--accent-hover);}
.btn.primary{background:var(--accent);color:#111827;border-color:var(--accent);font-weight:600;}
.btn.primary:hover{background:var(--accent-hover);color:#111827;}
.btn.sm{padding:4px 9px;font-size:11.5px;}
.btn.ghost{background:transparent;}
.toolbar{display:flex;gap:10px;align-items:center;margin-bottom:16px;flex-wrap:wrap;}
.toolbar .spacer{flex:1;}
input,select,textarea{font-family:inherit;}
.field{display:flex;flex-direction:column;gap:4px;margin-bottom:12px;}
.field label{font-size:11px;text-transform:uppercase;letter-spacing:.5px;color:var(--text-mute);font-weight:600;}
.field input,.field select,.field textarea{background:var(--bg);color:var(--text);border:1px solid var(--border-2);
  border-radius:8px;padding:8px 11px;font-size:13px;}
.field input:focus,.field select:focus,.field textarea:focus{outline:none;border-color:var(--accent);}
.field .unit{color:var(--text-mute);font-size:11px;}
.form-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:12px 16px;}

.callout{border:1px solid var(--border);border-left:4px solid var(--accent);background:var(--surface);
  color:var(--text-dim);padding:12px 16px;border-radius:8px;margin-bottom:18px;font-size:12.5px;line-height:1.55;}
.callout strong{color:var(--text);}
.callout.warn{border-left-color:var(--warn);}
.callout.sim{border-left-color:var(--bad);background:linear-gradient(90deg,rgba(248,113,113,.07),var(--surface));}

.strat-bar{height:16px;border-radius:4px;background:var(--accent);min-width:2px;}
.bar-row{display:grid;grid-template-columns:150px 1fr 130px;align-items:center;gap:10px;margin-bottom:7px;font-size:12.5px;}
.bar-row .v{text-align:right;color:var(--text-dim);font-variant-numeric:tabular-nums;}

.timeline{list-style:none;padding:0;margin:0;}
.timeline li{padding:9px 0 9px 20px;border-left:2px solid var(--border);position:relative;margin-left:4px;}
.timeline li::before{content:'';position:absolute;left:-6px;top:13px;width:9px;height:9px;border-radius:50%;
  background:var(--accent);border:2px solid var(--surface);}
.timeline .when{color:var(--text-mute);font-size:11px;}
.timeline .kind{font-size:10px;text-transform:uppercase;letter-spacing:.5px;color:var(--accent-hover);font-weight:700;}

.kv{display:grid;grid-template-columns:150px 1fr;gap:7px 14px;font-size:13px;}
.kv .k{color:var(--text-mute);}
.kv .v{color:var(--text);font-variant-numeric:tabular-nums;}

.big-val{font-size:30px;font-weight:700;font-variant-numeric:tabular-nums;letter-spacing:-.02em;}
.signal{display:inline-flex;align-items:center;gap:8px;padding:8px 16px;border-radius:10px;font-weight:700;font-size:15px;}
.signal.Release{background:var(--ok-dim);color:var(--ok);}
.signal.Retain{background:var(--info-dim);color:var(--info);}
.signal.Neutral{background:var(--warn-dim);color:var(--warn);}

.check{display:flex;align-items:center;gap:10px;padding:8px 0;border-bottom:1px solid var(--border);font-size:13px;}
.check:last-child{border-bottom:0;}
.check .nm{flex:1;color:var(--text-dim);}
.seg{display:inline-flex;gap:6px;margin-bottom:14px;flex-wrap:wrap;}
.seg a{padding:6px 12px;border:1px solid var(--border-2);border-radius:8px;color:var(--text-dim);
  background:var(--surface);font-size:12.5px;}
.seg a.active{background:var(--accent);color:#111827;border-color:var(--accent);font-weight:600;}

/* inline SVG chart frame */
.chart-frame{background:var(--bg);border:1px solid var(--border);border-radius:8px;padding:8px;}

/* login */
.login-wrap{height:100vh;display:flex;align-items:center;justify-content:center;
  background:radial-gradient(1200px 600px at 50% -10%,rgba(245,158,11,.10),transparent),var(--bg);}
.login-card{background:var(--surface);padding:36px 40px;border-radius:16px;width:380px;
  border:1px solid var(--border);box-shadow:0 30px 60px rgba(0,0,0,.4);}
.login-card h1{margin:0 0 4px;font-size:22px;display:flex;align-items:center;gap:9px;}
.login-card p{margin:0 0 20px;color:var(--text-mute);font-size:13px;}
.login-card input{width:100%;padding:11px 13px;border:1px solid var(--border-2);border-radius:9px;
  margin-bottom:11px;font-size:14px;background:var(--bg);color:var(--text);}
.login-card input:focus{outline:none;border-color:var(--accent);}
.login-card button{width:100%;padding:11px;font-weight:600;}
.login-card .error{color:var(--bad);font-size:12px;margin:4px 0;}
.login-card .hint{font-size:11.5px;color:var(--text-mute);margin-top:12px;text-align:center;}
"""

# (key, label, icon, href)
NAV = [
    ("OVERVIEW", [
        ("dashboard", "Dashboard", "▤", "/"),
        ("alerts", "Alerts", "◈", "/alerts"),
    ]),
    ("PORTFOLIO", [
        ("portfolios", "Portfolios", "▦", "/portfolios"),
        ("valuation", "Valuation & Analytics", "∿", "/valuation"),
    ]),
    ("MARKETPLACE", [
        ("crx", "CRX Exchange", "⇄", "/crx"),
        ("transfers", "Servicing Transfers", "→", "/transfers"),
    ]),
    ("GOVERNANCE", [
        ("compliance", "Compliance & Risk", "✓", "/compliance"),
        ("audit", "Audit Trail", "▣", "/audit"),
    ]),
    ("HELP", [
        ("guide", "User Guide", "?", "/guide"),
    ]),
]


def topbar(env: str, role: str, user_email: str | None):
    role_form = Form(
        Span("Acting as", cls=""),
        Select(*[Option(r, value=r, selected=(r == role)) for r in db.ROLES],
               name="role", onchange="this.form.submit()"),
        Input(type="hidden", name="next", value="", id="role-next"),
        method="post", action="/role", cls="role-switch",
    ) if user_email else None
    right = Div(
        role_form,
        Span(env, cls="env-pill"),
        A("Logout", href="/logout", cls="btn sm") if user_email else None,
        cls="actions",
    )
    return Div(
        Div(Span(cls="brand-dot"),
            Span("Fast", style="font-weight:800;"),
            Span("MSR", style="color:var(--accent);font-weight:700;letter-spacing:1px;"),
            cls="brand"),
        right, cls="topbar",
    )


def left_pane(active: str, badges: dict | None = None):
    badges = badges or {}
    sections = []
    for name, items in NAV:
        links = []
        for key, label, icon, href in items:
            badge = badges.get(key)
            links.append(A(
                Span(icon, cls="nav-icon"), Span(label),
                Span(str(badge), cls="nav-badge") if badge else None,
                href=href, cls=f"nav-item {'active' if active == key else ''}"))
        sections.append(Div(H4(name), *links, cls="nav-section"))
    return Div(*sections, cls="left-pane")


def page(active: str, env: str, role: str, user_email: str, *content):
    badges = {"alerts": db.scalar("SELECT COUNT(*) FROM alerts WHERE is_read=0") or 0,
              "transfers": db.scalar("SELECT COUNT(*) FROM exceptions WHERE status='Open'") or 0}
    badges = {k: v for k, v in badges.items() if v}
    return (
        Title("FastMSR"),
        Link(rel="icon", type="image/svg+xml", href="/static/favicon.svg"),
        Link(rel="preconnect", href="https://fonts.googleapis.com"),
        Link(rel="stylesheet",
             href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap"),
        Style(LAYOUT_CSS),
        Div(topbar(env, role, user_email), left_pane(active, badges),
            Div(*content, cls="center-pane"), cls="app"),
        Script("(function(){var n=document.getElementById('role-next');"
               "if(n)n.value=location.pathname+location.search;})();"),
    )


# --- small view helpers -----------------------------------------------------

def title(t: str, sub: str = "", *actions):
    return Div(Div(H1(t), P(sub, cls="sub") if sub else None),
               Div(*actions, style="display:flex;gap:10px;") if actions else None,
               cls="page-title")


def kpi(label, value, trend="", tone=""):
    val = f"{value:,}" if isinstance(value, (int, float)) and not isinstance(value, bool) else str(value)
    return Div(Div(label, cls="label"), Div(val, cls="value"),
               Div(trend, cls="trend") if trend else None, cls=f"kpi {tone}".strip())


def pill(text, kind=""):
    cls = "pill " + (kind or str(text)).lower().replace(" ", "").replace("/", "").replace("+", "")
    return Span(text, cls=cls)


def money(v) -> str:
    v = v or 0
    neg = v < 0
    v = abs(v)
    if v >= 1_000_000:
        s = f"${v/1_000_000:.2f}M"
    elif v >= 1_000:
        s = f"${v/1_000:.1f}k"
    else:
        s = f"${v:,.0f}"
    return ("-" + s) if neg else s


def money0(v) -> str:
    v = v or 0
    return f"${v:,.0f}"


def pct(v, dp=2) -> str:
    return f"{v*100:.{dp}f}%"
