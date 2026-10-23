"""Industrial UI design system for Lianbo Project Performance Hub (v10).

One consolidated stylesheet replaces the eleven overlapping CSS blocks of
earlier versions, plus small HTML helpers so every module uses the same page
header, section titles, KPI tiles, status chips and ticket cards.
"""
from __future__ import annotations

import html as _html
from typing import Iterable, Optional

# ---------------------------------------------------------------------------
# Design tokens
# ---------------------------------------------------------------------------
COLORS = {
    "bg": "#0A1120",
    "panel": "#101A2C",
    "panel_2": "#15223A",
    "line": "rgba(148,163,184,0.16)",
    "text": "#E6EDF7",
    "muted": "#93A4BC",
    "accent": "#22D3EE",
    "accent_2": "#3B82F6",
    "ok": "#22C55E",
    "warn": "#F59E0B",
    "alarm": "#EF4444",
    "info": "#A78BFA",
}

# Industrial chart palette: cyan, steel blue, amber, green, violet, rose, slate, red
CHART_COLORS = ["#22D3EE", "#3B82F6", "#F59E0B", "#22C55E", "#A78BFA", "#F472B6", "#94A3B8", "#EF4444"]

STATUS_COLORS = {"ok": COLORS["ok"], "warn": COLORS["warn"], "alarm": COLORS["alarm"], "info": COLORS["accent"], "neutral": "#64748B"}


def esc(value) -> str:
    return _html.escape("" if value is None else str(value))


# ---------------------------------------------------------------------------
# Stylesheet
# ---------------------------------------------------------------------------
def theme_css(background_css: str = "") -> str:
    return f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

:root {{
    --bg: {COLORS['bg']};
    --panel: {COLORS['panel']};
    --panel-2: {COLORS['panel_2']};
    --line: {COLORS['line']};
    --text: {COLORS['text']};
    --muted: {COLORS['muted']};
    --accent: {COLORS['accent']};
    --accent-2: {COLORS['accent_2']};
    --ok: {COLORS['ok']};
    --warn: {COLORS['warn']};
    --alarm: {COLORS['alarm']};
    --radius: 14px;
    --shadow: 0 10px 30px rgba(0,0,0,0.28);
}}

html, body, .stApp, [class*="css"] {{
    font-family: "Inter", "Segoe UI", Roboto, Arial, sans-serif !important;
    color: var(--text);
}}
{background_css}

/* ---------- Streamlit chrome ---------- */
#MainMenu, footer, [data-testid="stToolbar"], [data-testid="stDecoration"],
[data-testid="stStatusWidget"], [data-testid="stDeployButton"], .stAppDeployButton {{
    display: none !important;
}}
header[data-testid="stHeader"] {{ background: transparent !important; height: 0 !important; min-height: 0 !important; }}
.block-container {{ padding: 1rem 1.6rem 3rem 1.6rem !important; max-width: 100% !important; }}
[data-testid="InputInstructions"] {{ display: none !important; }}

/* ---------- Typography ---------- */
h1, h2, h3, h4 {{ color: var(--text) !important; letter-spacing: -0.01em; font-weight: 700 !important; }}
h2 {{ font-size: 1.45rem !important; }}
h3 {{
    font-size: 1.08rem !important;
    margin-top: 1.1rem !important;
    padding: 2px 0 2px 12px;
    border-left: 3px solid var(--accent);
}}
h4 {{ font-size: 0.98rem !important; color: #CFE3F7 !important; }}
p, li, label, span {{ color: var(--text); }}
[data-testid="stCaptionContainer"], .stCaption, small {{ color: var(--muted) !important; }}
code {{ color: var(--accent) !important; background: rgba(34,211,238,0.08) !important; }}

/* ---------- Top bar ---------- */
.app-header {{
    display: flex; align-items: center; gap: 16px;
    padding: 12px 16px; margin: 0 0 14px 0;
    border-radius: var(--radius);
    background: linear-gradient(120deg, rgba(16,26,44,0.96), rgba(21,34,58,0.90));
    border: 1px solid var(--line);
    box-shadow: var(--shadow);
}}
.app-logo {{ height: 42px; width: auto; background: #fff; padding: 6px 10px; border-radius: 10px; }}
.app-title-wrap {{ display: flex; flex-direction: column; min-width: 0; flex: 1; }}
.app-title {{ font-size: 1.2rem; font-weight: 800; color: var(--text); line-height: 1.15; }}
.app-subtitle {{ font-size: 0.78rem; color: var(--muted); margin-top: 2px; }}
.app-version {{ font-size: 0.7rem; color: var(--accent); }}
.app-header-right {{ display: flex; gap: 8px; flex-wrap: wrap; justify-content: flex-end; }}

/* ---------- Page header (per module) ---------- */
.page-head {{
    display: flex; align-items: center; gap: 14px;
    margin: 4px 0 16px 0; padding: 14px 16px;
    border-radius: var(--radius);
    background: var(--panel);
    border: 1px solid var(--line);
    border-left: 4px solid var(--accent);
}}
.page-head-icon {{
    width: 46px; height: 46px; flex: 0 0 46px;
    display: flex; align-items: center; justify-content: center;
    font-size: 24px; border-radius: 12px;
    background: rgba(34,211,238,0.10); border: 1px solid rgba(34,211,238,0.28);
}}
.page-head-title {{ font-size: 1.35rem; font-weight: 800; color: var(--text); line-height: 1.15; }}
.page-head-sub {{ font-size: 0.85rem; color: var(--muted); margin-top: 3px; }}
.page-head-chips {{ margin-left: auto; display: flex; gap: 6px; flex-wrap: wrap; justify-content: flex-end; }}

/* ---------- Section head ---------- */
.section-head {{ display: flex; align-items: baseline; gap: 10px; margin: 18px 0 8px 0; }}
.section-head .section-title {{
    font-size: 0.82rem; font-weight: 800; letter-spacing: 0.08em; text-transform: uppercase; color: #CFE3F7;
}}
.section-head .section-line {{ flex: 1; height: 1px; background: var(--line); }}
.section-head .section-caption {{ font-size: 0.78rem; color: var(--muted); }}

/* ---------- Chips ---------- */
.chip {{
    display: inline-flex; align-items: center; gap: 6px;
    padding: 3px 10px; border-radius: 999px;
    font-size: 0.74rem; font-weight: 600; white-space: nowrap;
    background: rgba(148,163,184,0.10); color: #CBD5E1; border: 1px solid var(--line);
}}
.chip .dot {{ width: 7px; height: 7px; border-radius: 50%; display: inline-block; }}
.chip-ok {{ background: rgba(34,197,94,0.12); color: #86EFAC; border-color: rgba(34,197,94,0.35); }}
.chip-warn {{ background: rgba(245,158,11,0.12); color: #FCD34D; border-color: rgba(245,158,11,0.35); }}
.chip-alarm {{ background: rgba(239,68,68,0.12); color: #FCA5A5; border-color: rgba(239,68,68,0.35); }}
.chip-info {{ background: rgba(34,211,238,0.10); color: #A5F3FC; border-color: rgba(34,211,238,0.32); }}

/* ---------- KPI tiles ---------- */
.kpi-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 12px; margin: 6px 0 14px 0; }}
.kpi-card {{
    position: relative; overflow: hidden;
    padding: 14px 16px 12px 16px; border-radius: var(--radius);
    background: linear-gradient(160deg, var(--panel-2), var(--panel));
    border: 1px solid var(--line);
    box-shadow: 0 6px 18px rgba(0,0,0,0.20);
}}
.kpi-card::before {{ content: ""; position: absolute; left: 0; top: 0; bottom: 0; width: 4px; background: var(--kpi-color, var(--accent)); }}
.kpi-label {{ font-size: 0.72rem; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase; color: var(--muted); }}
.kpi-value {{ font-size: 1.75rem; font-weight: 800; color: var(--text); margin-top: 4px; font-variant-numeric: tabular-nums; line-height: 1.1; }}
.kpi-unit {{ font-size: 0.85rem; font-weight: 600; color: var(--muted); margin-left: 4px; }}
.kpi-foot {{ font-size: 0.74rem; color: var(--muted); margin-top: 6px; display: flex; align-items: center; gap: 6px; }}
.kpi-bar {{ height: 5px; border-radius: 999px; background: rgba(148,163,184,0.16); margin-top: 8px; overflow: hidden; }}
.kpi-bar > span {{ display: block; height: 100%; border-radius: 999px; background: var(--kpi-color, var(--accent)); }}

/* Streamlit metric widget in the same style */
[data-testid="stMetric"] {{
    background: linear-gradient(160deg, var(--panel-2), var(--panel));
    border: 1px solid var(--line); border-left: 4px solid var(--accent);
    border-radius: var(--radius); padding: 12px 14px;
}}
[data-testid="stMetricLabel"] p {{ font-size: 0.72rem !important; font-weight: 700 !important; letter-spacing: 0.05em; text-transform: uppercase; color: var(--muted) !important; }}
[data-testid="stMetricValue"] {{ font-size: 1.6rem !important; font-weight: 800 !important; color: var(--text) !important; font-variant-numeric: tabular-nums; }}

/* Evaluation grade cards */
.metric-card {{
    padding: 14px 16px; border-radius: var(--radius);
    background: linear-gradient(160deg, var(--panel-2), var(--panel));
    border: 1px solid var(--line); border-top: 3px solid var(--accent); text-align: center;
}}
.metric-title {{ font-size: 0.74rem; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase; color: var(--muted); }}
.metric-value {{ font-size: 2.2rem; font-weight: 800; color: var(--text); margin: 4px 0; }}
.metric-delta {{ font-size: 0.8rem; color: #A5F3FC; }}

/* ---------- OEE progress tiles ---------- */
.oee-card-row {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin: 8px 0 18px 0; }}
.oee-progress-card {{
    padding: 14px 16px; border-radius: var(--radius); min-height: 122px;
    background: linear-gradient(160deg, var(--panel-2), var(--panel)); border: 1px solid var(--line);
}}
.oee-progress-card.main {{ border-color: rgba(34,197,94,0.45); box-shadow: 0 0 0 1px rgba(34,197,94,0.15) inset; }}
.oee-card-label {{ font-size: 0.72rem; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase; color: var(--muted); }}
.oee-card-value {{ font-size: 2rem; font-weight: 800; color: var(--text); margin: 6px 0 10px 0; font-variant-numeric: tabular-nums; }}
.oee-progress-track {{ height: 8px; border-radius: 999px; background: rgba(148,163,184,0.16); overflow: hidden; }}
.oee-progress-fill {{ height: 100%; border-radius: 999px; }}
.oee-card-footer {{ font-size: 0.74rem; color: var(--muted); margin-top: 8px; }}

/* ---------- Sidebar ---------- */
section[data-testid="stSidebar"] {{
    background: linear-gradient(180deg, #0B1424 0%, #0A1120 100%) !important;
    border-right: 1px solid var(--line);
}}
section[data-testid="stSidebar"] [data-testid="stSidebarHeader"] {{ display: none !important; }}
section[data-testid="stSidebar"] .block-container, section[data-testid="stSidebar"] > div {{ padding-top: 0.6rem !important; }}
.side-brand {{
    display: flex; align-items: center; gap: 10px; padding: 10px 10px 12px 10px;
    border-bottom: 1px solid var(--line); margin-bottom: 10px;
}}
.side-brand-mark {{
    width: 34px; height: 34px; border-radius: 9px; display: flex; align-items: center; justify-content: center;
    background: linear-gradient(135deg, var(--accent), var(--accent-2)); color: #06202A; font-weight: 900; font-size: 15px;
}}
.side-brand-text {{ font-weight: 800; font-size: 0.95rem; color: var(--text); line-height: 1.1; }}
.side-brand-text small {{ display: block; font-weight: 500; font-size: 0.7rem; color: var(--muted) !important; }}
.user-badge {{
    display: flex; align-items: center; gap: 10px; padding: 10px; margin: 2px 0 10px 0;
    border-radius: 12px; background: rgba(148,163,184,0.06); border: 1px solid var(--line);
}}
.user-avatar {{
    width: 34px; height: 34px; border-radius: 50%; flex: 0 0 34px;
    display: flex; align-items: center; justify-content: center;
    background: rgba(34,211,238,0.14); color: var(--accent); font-weight: 800; font-size: 0.85rem;
}}
.user-name {{ font-weight: 700; font-size: 0.88rem; color: var(--text); line-height: 1.15; }}
.user-role {{ font-size: 0.72rem; color: var(--muted); }}
.nav-group {{
    font-size: 0.66rem; font-weight: 800; letter-spacing: 0.12em; text-transform: uppercase;
    color: #6B7F99; margin: 14px 4px 6px 4px;
}}
section[data-testid="stSidebar"] .stButton > button {{
    justify-content: flex-start !important; text-align: left !important;
    min-height: 40px; margin-bottom: 2px;
    background: transparent !important; border: 1px solid transparent !important;
    color: #C9D6E8 !important; font-weight: 600 !important; box-shadow: none !important;
}}
section[data-testid="stSidebar"] .stButton > button:hover {{
    background: rgba(148,163,184,0.08) !important; border-color: var(--line) !important; color: #fff !important;
}}
section[data-testid="stSidebar"] .stButton > button[kind="primary"],
section[data-testid="stSidebar"] .stButton > button[data-testid="stBaseButton-primary"] {{
    background: linear-gradient(90deg, rgba(34,211,238,0.18), rgba(59,130,246,0.08)) !important;
    border: 1px solid rgba(34,211,238,0.35) !important;
    border-left: 3px solid var(--accent) !important;
    color: #FFFFFF !important;
}}
section[data-testid="stSidebar"] hr {{ border-color: var(--line) !important; margin: 10px 0 !important; }}
.side-foot {{ font-size: 0.7rem; color: #6B7F99; margin-top: 8px; }}

/* ---------- Buttons (main area) ---------- */
.stButton > button, .stDownloadButton > button, [data-testid="stFormSubmitButton"] button {{
    border-radius: 10px !important; min-height: 40px; font-weight: 650 !important;
    background: var(--panel-2) !important; color: var(--text) !important;
    border: 1px solid rgba(148,163,184,0.26) !important;
    transition: border-color .15s ease, background .15s ease, transform .15s ease;
}}
.stButton > button:hover, .stDownloadButton > button:hover, [data-testid="stFormSubmitButton"] button:hover {{
    border-color: var(--accent) !important; color: #fff !important; transform: translateY(-1px);
}}
.stButton > button[kind="primary"], [data-testid="stFormSubmitButton"] button[kind="primary"],
.stButton > button[data-testid="stBaseButton-primary"], [data-testid="stFormSubmitButton"] button[kind="primaryFormSubmit"] {{
    background: linear-gradient(135deg, #0EA5C6, #2563EB) !important; border: 1px solid rgba(34,211,238,0.6) !important; color: #fff !important;
}}
[data-testid="stFormSubmitButton"] button {{
    background: linear-gradient(135deg, #0EA5C6, #2563EB) !important; border: 1px solid rgba(34,211,238,0.6) !important; color: #fff !important;
}}
button:disabled, button[disabled] {{ opacity: 0.55 !important; cursor: not-allowed !important; transform: none !important; }}

/* ---------- Inputs ---------- */
.stTextInput input, .stNumberInput input, .stDateInput input, .stTimeInput input, .stTextArea textarea,
div[data-baseweb="select"] > div, div[data-baseweb="input"] {{
    background: #0D1729 !important; color: var(--text) !important; -webkit-text-fill-color: var(--text) !important;
    border-color: rgba(148,163,184,0.28) !important; border-radius: 10px !important;
}}
.stTextInput input:focus, .stTextArea textarea:focus, .stNumberInput input:focus {{
    border-color: var(--accent) !important; box-shadow: 0 0 0 2px rgba(34,211,238,0.18) !important;
}}
input::placeholder, textarea::placeholder {{ color: #6B7F99 !important; -webkit-text-fill-color: #6B7F99 !important; }}
input:-webkit-autofill {{ -webkit-box-shadow: 0 0 0 1000px #0D1729 inset !important; -webkit-text-fill-color: var(--text) !important; }}
div[data-baseweb="select"] span, div[data-baseweb="select"] input {{ color: var(--text) !important; -webkit-text-fill-color: var(--text) !important; }}
div[data-baseweb="popover"] ul, div[data-baseweb="menu"], ul[role="listbox"] {{ background: #0D1729 !important; border: 1px solid var(--line) !important; }}
li[role="option"] {{ color: var(--text) !important; }}
li[role="option"]:hover, li[aria-selected="true"] {{ background: rgba(34,211,238,0.14) !important; }}
label, [data-testid="stWidgetLabel"] p {{ color: #CFE3F7 !important; font-weight: 600 !important; font-size: 0.84rem !important; }}

/* ---------- Segmented navigation (horizontal radios) ---------- */
div[role="radiogroup"][aria-orientation="horizontal"], .stRadio div[role="radiogroup"] {{
    display: flex !important; flex-wrap: wrap; gap: 6px !important;
    padding: 5px !important; border-radius: 12px;
    background: rgba(13,23,41,0.85); border: 1px solid var(--line);
}}
.stRadio div[role="radiogroup"] > label {{
    margin: 0 !important; padding: 7px 14px !important; border-radius: 9px;
    border: 1px solid transparent; cursor: pointer; transition: background .15s ease;
}}
.stRadio div[role="radiogroup"] > label > div:first-child {{ display: none !important; }}
.stRadio div[role="radiogroup"] > label p {{ font-size: 0.84rem !important; font-weight: 650 !important; color: #A9B9CF !important; }}
.stRadio div[role="radiogroup"] > label:hover {{ background: rgba(148,163,184,0.08); }}
.stRadio div[role="radiogroup"] > label:has(input:checked) {{
    background: linear-gradient(135deg, rgba(34,211,238,0.22), rgba(59,130,246,0.18));
    border-color: rgba(34,211,238,0.45);
}}
.stRadio div[role="radiogroup"] > label:has(input:checked) p {{ color: #FFFFFF !important; }}
.nav-level-2 .stRadio div[role="radiogroup"] {{ background: transparent; border: none; padding: 0 !important; }}

/* ---------- Tabs ---------- */
.stTabs [data-baseweb="tab-list"] {{ gap: 4px; border-bottom: 1px solid var(--line); background: transparent; }}
.stTabs [data-baseweb="tab"] {{
    padding: 8px 14px; border-radius: 10px 10px 0 0; color: #A9B9CF; font-weight: 650; background: transparent;
}}
.stTabs [aria-selected="true"] {{ color: #fff !important; background: rgba(34,211,238,0.10) !important; }}
.stTabs [data-baseweb="tab-highlight"] {{ background-color: var(--accent) !important; }}
.stTabs, .stTabs * {{ pointer-events: auto; }}

/* ---------- Panels ---------- */
[data-testid="stPlotlyChart"] {{
    background: var(--panel); border: 1px solid var(--line); border-radius: var(--radius);
    padding: 6px 8px; box-shadow: 0 6px 18px rgba(0,0,0,0.18);
}}
[data-testid="stDataFrame"], [data-testid="stTable"] {{ border: 1px solid var(--line); border-radius: var(--radius); overflow: hidden; }}
[data-testid="stForm"] {{ background: rgba(16,26,44,0.75); border: 1px solid var(--line) !important; border-radius: var(--radius) !important; padding: 16px !important; }}
[data-testid="stExpander"] details {{ background: rgba(16,26,44,0.6); border: 1px solid var(--line) !important; border-radius: 12px !important; }}
[data-testid="stVerticalBlockBorderWrapper"] {{ border-color: var(--line) !important; border-radius: var(--radius) !important; }}
hr {{ border-color: var(--line) !important; }}

/* ---------- Alerts ---------- */
.stAlert {{ border-radius: 12px !important; border: 1px solid var(--line) !important; }}
.alert-red, .alert-yellow, .alert-green {{ border-radius: 12px; padding: 12px 14px; margin-bottom: 10px; color: var(--text); }}
.alert-red {{ background: rgba(239,68,68,0.10); border: 1px solid rgba(239,68,68,0.35); border-left: 4px solid var(--alarm); }}
.alert-yellow {{ background: rgba(245,158,11,0.10); border: 1px solid rgba(245,158,11,0.35); border-left: 4px solid var(--warn); }}
.alert-green {{ background: rgba(34,197,94,0.10); border: 1px solid rgba(34,197,94,0.35); border-left: 4px solid var(--ok); }}

/* ---------- Work ticket cards ---------- */
.kanban-head {{
    display: flex; align-items: center; justify-content: space-between;
    padding: 10px 12px; margin-bottom: 10px; border-radius: 12px;
    background: var(--panel); border: 1px solid var(--line); border-top: 3px solid var(--kanban-color, var(--accent));
}}
.kanban-head .kanban-title {{ font-weight: 800; font-size: 0.9rem; letter-spacing: 0.04em; text-transform: uppercase; color: var(--text); }}
.kanban-head .kanban-count {{
    min-width: 26px; text-align: center; padding: 2px 8px; border-radius: 999px;
    font-size: 0.78rem; font-weight: 800; background: rgba(148,163,184,0.14); color: var(--text);
}}
.ticket-card {{
    position: relative; padding: 12px 12px 10px 14px; margin-bottom: 8px; border-radius: 12px;
    background: linear-gradient(160deg, var(--panel-2), var(--panel)); border: 1px solid var(--line);
}}
.ticket-card::before {{ content: ""; position: absolute; left: 0; top: 10px; bottom: 10px; width: 3px; border-radius: 3px; background: var(--prio-color, #64748B); }}
.ticket-title {{ font-weight: 750; font-size: 0.95rem; color: var(--text); line-height: 1.25; margin-bottom: 6px; }}
.ticket-meta {{ display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 6px; }}
.ticket-line {{ font-size: 0.76rem; color: var(--muted); line-height: 1.45; }}
.ticket-line b {{ color: #CFE3F7; font-weight: 650; }}

/* ---------- Login ---------- */
.login-card {{
    max-width: 430px; margin: 30px auto 0 auto; padding: 28px 32px 18px 32px; text-align: center;
    border-radius: 18px 18px 0 0; background: linear-gradient(160deg, var(--panel-2), var(--panel));
    border: 1px solid var(--line); border-bottom: none; box-shadow: var(--shadow);
}}
.login-logo {{ height: 58px; background: #fff; padding: 8px 12px; border-radius: 12px; margin-bottom: 14px; }}
.login-title {{ font-size: 1.6rem; font-weight: 800; color: var(--text); }}
.login-subtitle {{ font-size: 0.82rem; color: var(--muted); }}
.login-helper {{ text-align: center; color: var(--muted); font-size: 0.72rem; margin-top: 8px; }}

/* ---------- Add-task button ---------- */
.st-key-create_my_task_toggle button {{
    min-height: 44px !important; padding: 0 18px !important; white-space: pre-line !important;
    background: linear-gradient(135deg, #0EA5C6, #2563EB) !important; border: 1px solid rgba(34,211,238,0.6) !important; color: #fff !important;
}}

/* ---------- Password eye: icon only ---------- */
.stTextInput:has(input[type="password"]) button {{ min-width: 36px !important; }}

/* ---------- Mobile navigation (hidden on desktop) ---------- */
.mobile-menu-title, [class*="st-key-mobile_nav_"], .st-key-mobile_logout_btn, .st-key-mobile_refresh_btn {{ display: none !important; }}

@media (max-width: 1100px) {{
    .oee-card-row {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
}}
@media (max-width: 768px) {{
    .block-container {{ padding: 0.6rem 0.7rem 2rem 0.7rem !important; }}
    section[data-testid="stSidebar"], [data-testid="collapsedControl"], [data-testid="stSidebarCollapseButton"] {{ display: none !important; }}
    .mobile-menu-title, [class*="st-key-mobile_nav_"], .st-key-mobile_logout_btn, .st-key-mobile_refresh_btn {{ display: block !important; }}
    .mobile-menu-title {{
        font-size: 0.7rem; font-weight: 800; letter-spacing: 0.12em; text-transform: uppercase; color: var(--muted);
        margin: 4px 2px 6px 2px;
    }}
    [class*="st-key-mobile_nav_"] button {{ justify-content: flex-start !important; min-height: 44px; }}
    .app-header {{ padding: 10px; gap: 10px; }}
    .app-logo {{ height: 34px; }}
    .app-title {{ font-size: 1rem; }}
    .app-subtitle, .app-header-right {{ display: none; }}
    .page-head {{ padding: 10px 12px; }}
    .page-head-title {{ font-size: 1.1rem; }}
    .page-head-chips {{ display: none; }}
    .kpi-grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }}
    .kpi-value {{ font-size: 1.35rem; }}
    .oee-card-row {{ grid-template-columns: 1fr 1fr; gap: 8px; }}
    .oee-card-value {{ font-size: 1.5rem; }}
    .stApp, .block-container {{ overflow-x: hidden !important; }}
    .stRadio, .stRadio > div {{ max-width: 100% !important; min-width: 0 !important; }}
    .stRadio div[role="radiogroup"] {{ flex-wrap: nowrap !important; overflow-x: auto; scrollbar-width: none; max-width: 100%; }}
    .section-head {{ flex-wrap: wrap; }}
    .section-head .section-line {{ display: none; }}
    .stRadio div[role="radiogroup"] > label {{ white-space: nowrap; }}
    [data-testid="stHorizontalBlock"] {{ flex-wrap: wrap !important; gap: 0.5rem !important; }}
    [data-testid="column"], [data-testid="stColumn"] {{ min-width: calc(50% - 0.5rem) !important; flex: 1 1 calc(50% - 0.5rem) !important; }}
    .login-card {{ margin-top: 10px; padding: 22px 18px 14px 18px; }}
}}
@media (max-width: 420px) {{
    [data-testid="column"], [data-testid="stColumn"] {{ min-width: 100% !important; flex: 1 1 100% !important; }}
    .kpi-grid {{ grid-template-columns: 1fr 1fr; }}
}}
</style>
"""


# ---------------------------------------------------------------------------
# HTML helpers
# ---------------------------------------------------------------------------
def chip(text, status: str = "", dot: bool = False) -> str:
    cls = f"chip chip-{status}" if status else "chip"
    color = STATUS_COLORS.get(status, "#94A3B8")
    dot_html = f'<span class="dot" style="background:{color}"></span>' if dot else ""
    return f'<span class="{cls}">{dot_html}{esc(text)}</span>'


def page_header(icon: str, title: str, subtitle: str = "", chips: Iterable[str] = ()) -> str:
    chips_html = "".join(chips)
    return (
        '<div class="page-head">'
        f'<div class="page-head-icon">{esc(icon)}</div>'
        f'<div><div class="page-head-title">{esc(title)}</div>'
        + (f'<div class="page-head-sub">{esc(subtitle)}</div>' if subtitle else "")
        + "</div>"
        + (f'<div class="page-head-chips">{chips_html}</div>' if chips_html else "")
        + "</div>"
    )


def section(title: str, caption: str = "") -> str:
    return (
        '<div class="section-head">'
        f'<span class="section-title">{esc(title)}</span>'
        '<span class="section-line"></span>'
        + (f'<span class="section-caption">{esc(caption)}</span>' if caption else "")
        + "</div>"
    )


def kpi_card(label: str, value: str, unit: str = "", status: str = "info", foot: str = "", progress: Optional[float] = None) -> str:
    color = STATUS_COLORS.get(status, COLORS["accent"])
    bar = ""
    if progress is not None:
        width = max(0.0, min(float(progress), 100.0))
        bar = f'<div class="kpi-bar"><span style="width:{width:.1f}%"></span></div>'
    return (
        f'<div class="kpi-card" style="--kpi-color:{color}">'
        f'<div class="kpi-label">{esc(label)}</div>'
        f'<div class="kpi-value">{esc(value)}<span class="kpi-unit">{esc(unit)}</span></div>'
        f"{bar}"
        + (f'<div class="kpi-foot">{foot}</div>' if foot else "")
        + "</div>"
    )


def kpi_grid(cards: Iterable[str]) -> str:
    return '<div class="kpi-grid">' + "".join(cards) + "</div>"


def status_for(value: float, target: float, warn_ratio: float = 0.85, higher_is_better: bool = True) -> str:
    """ok / warn / alarm compared with a target."""
    try:
        value, target = float(value), float(target)
    except (TypeError, ValueError):
        return "neutral"
    if target <= 0:
        return "info"
    ratio = value / target if higher_is_better else (target / value if value else 1e9)
    if ratio >= 1:
        return "ok"
    if ratio >= warn_ratio:
        return "warn"
    return "alarm"


def initials(name: str) -> str:
    parts = [p for p in str(name or "").split() if p]
    if not parts:
        return "?"
    return (parts[0][0] + (parts[-1][0] if len(parts) > 1 else "")).upper()


def format_number(value, decimals: int = 1) -> str:
    """Serbian number format: 1.234,5"""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "–"
    text = f"{number:,.{decimals}f}"
    return text.replace(",", "X").replace(".", ",").replace("X", ".")
