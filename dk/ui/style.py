"""Custom CSS + Plotly theming for the DK Investing dashboard. Dark + light modes."""
from __future__ import annotations
import streamlit as st

# Accent colors — identical in both modes (mint/coral/azure read well on either).
ACCENT = "#00d4aa"        # mint — primary accent / bull
ACCENT_2 = "#4ea1ff"      # azure — secondary
BULL = "#00d4aa"
BEAR = "#ff5d5d"
NEUTRAL = "#7c8aa8"
WARN = "#ffb547"

# Surface colors — MUTABLE; set_mode() swaps these between dark and light.
BG = "#0b0f1a"
CARD = "#151b2c"
CARD_HOVER = "#1c2440"
BORDER = "#2a3550"
TEXT = "#e8ecf4"
TEXT_DIM = "#8b95ad"

_DARK = dict(BG="#0b0f1a", CARD="#151b2c", CARD_HOVER="#1c2440",
             BORDER="#2a3550", TEXT="#e8ecf4", TEXT_DIM="#8b95ad")
_LIGHT = dict(BG="#f4f6fb", CARD="#ffffff", CARD_HOVER="#eef2fa",
              BORDER="#d9dfea", TEXT="#16203a", TEXT_DIM="#5d6b86")

MODE = "dark"


def set_mode(mode: str) -> None:
    """Swap the surface palette globals so inline HTML cards adapt to the mode."""
    global BG, CARD, CARD_HOVER, BORDER, TEXT, TEXT_DIM, MODE
    p = _LIGHT if mode == "light" else _DARK
    BG, CARD, CARD_HOVER = p["BG"], p["CARD"], p["CARD_HOVER"]
    BORDER, TEXT, TEXT_DIM = p["BORDER"], p["TEXT"], p["TEXT_DIM"]
    MODE = mode

CSS = f"""
<style>
/* ---------- App-wide base ---------- */
.stApp {{
    background:
      radial-gradient(1100px 600px at 8% -10%, rgba(0,212,170,0.06), transparent 60%),
      radial-gradient(900px 500px at 95% 0%, rgba(78,161,255,0.07), transparent 55%),
      linear-gradient(180deg, {BG} 0%, #080c14 100%);
    color: {TEXT};
}}

/* Give breathing room above brand bar so Streamlit toolbar doesn't clip it */
.block-container {{
    padding-top: 3.2rem !important;
    padding-bottom: 3rem !important;
    max-width: 1500px;
}}

/* Streamlit's top decoration line — make it match our accent */
[data-testid="stDecoration"] {{
    background: linear-gradient(90deg, {ACCENT}, {ACCENT_2}) !important;
    height: 3px !important;
}}

/* Top filter toolbar */
.dk-toolbar {{
    background: {CARD};
    border: 1px solid {BORDER};
    border-radius: 12px;
    padding: 12px 16px;
    margin: 0 0 14px 0;
    display: flex; flex-wrap: wrap; align-items: center; gap: 14px;
    box-shadow: 0 2px 12px rgba(0,0,0,0.25);
}}
.dk-toolbar-label {{
    color: {TEXT_DIM}; font-size: 11px; font-weight: 700;
    text-transform: uppercase; letter-spacing: 1.4px;
}}

/* ---------- Sidebar ---------- */
[data-testid="stSidebar"] {{
    background: linear-gradient(180deg, #0c111d 0%, #0a0e18 100%);
    border-right: 1px solid {BORDER};
}}
[data-testid="stSidebar"] [data-testid="stSidebarNavCollapseButton"] {{ color: {TEXT_DIM}; }}

[data-testid="stSidebar"] h1,
[data-testid="stSidebar"] h2,
[data-testid="stSidebar"] h3 {{
    color: {TEXT};
    letter-spacing: 0.3px;
}}

.sidebar-section-title {{
    color: {TEXT_DIM};
    font-size: 11px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 1.6px;
    margin: 1.1rem 0 0.4rem 0;
    padding-bottom: 0.35rem;
    border-bottom: 1px solid {BORDER};
}}

/* ---------- Top brand bar ---------- */
.dk-brand {{
    display: flex; align-items: center; justify-content: space-between;
    padding: 14px 18px; margin: 0 0 14px 0;
    background: linear-gradient(135deg, rgba(0,212,170,0.10) 0%, rgba(78,161,255,0.06) 100%);
    border: 1px solid {BORDER};
    border-radius: 14px;
    box-shadow: 0 4px 24px rgba(0,0,0,0.35);
}}
.dk-brand-left {{ display: flex; align-items: center; gap: 14px; }}
.dk-brand-logo {{
    width: 38px; height: 38px; border-radius: 10px;
    background: linear-gradient(135deg, {ACCENT} 0%, {ACCENT_2} 100%);
    display: grid; place-items: center; font-weight: 800; color: #062019;
    font-size: 18px; box-shadow: 0 4px 16px rgba(0,212,170,0.35);
}}
.dk-brand-title {{ font-size: 20px; font-weight: 700; line-height: 1.1; }}
.dk-brand-sub  {{ font-size: 12px; color: {TEXT_DIM}; }}
.dk-brand-clock {{
    font-family: ui-monospace, "JetBrains Mono", Menlo, monospace;
    color: {TEXT_DIM}; font-size: 13px;
}}

/* ---------- KPI strip ---------- */
.kpi-grid {{
    display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px;
    margin: 0 0 18px 0;
}}
.kpi {{
    background: {CARD};
    border: 1px solid {BORDER};
    border-radius: 12px;
    padding: 14px 16px;
    transition: transform .15s ease, border-color .15s ease, box-shadow .15s ease;
    position: relative; overflow: hidden;
}}
.kpi:hover {{
    transform: translateY(-1px);
    border-color: {ACCENT};
    box-shadow: 0 6px 20px rgba(0,0,0,0.45);
}}
.kpi::before {{
    content: ""; position: absolute; left: 0; top: 0; bottom: 0; width: 3px;
    background: linear-gradient(180deg, {ACCENT}, {ACCENT_2});
    opacity: 0.85;
}}
.kpi-label {{
    color: {TEXT_DIM}; font-size: 11px; font-weight: 600;
    text-transform: uppercase; letter-spacing: 1.2px;
    margin-bottom: 6px;
}}
.kpi-value {{ color: {TEXT}; font-size: 22px; font-weight: 700; line-height: 1.1; }}
.kpi-sub   {{ color: {TEXT_DIM}; font-size: 12px; margin-top: 4px; }}
.kpi.bull  {{ }}
.kpi.bull .kpi-value {{ color: {BULL}; }}
.kpi.bear .kpi-value {{ color: {BEAR}; }}
.kpi.warn .kpi-value {{ color: {WARN}; }}

/* ---------- Tabs ---------- */
.stTabs [data-baseweb="tab-list"] {{
    gap: 4px;
    background: transparent;
    border-bottom: 1px solid {BORDER};
    padding-bottom: 2px;
}}
.stTabs [data-baseweb="tab"] {{
    background: transparent;
    color: {TEXT_DIM};
    font-weight: 600;
    border-radius: 8px 8px 0 0;
    padding: 8px 14px;
    border: 1px solid transparent;
    border-bottom: none;
}}
.stTabs [data-baseweb="tab"]:hover {{
    color: {TEXT};
    background: rgba(255,255,255,0.03);
}}
.stTabs [aria-selected="true"] {{
    background: {CARD} !important;
    color: {ACCENT} !important;
    border: 1px solid {BORDER} !important;
    border-bottom: 1px solid {CARD} !important;
}}

/* ---------- Buttons ---------- */
.stButton > button {{
    border-radius: 10px;
    border: 1px solid {BORDER};
    background: {CARD};
    color: {TEXT};
    transition: all .15s ease;
}}
.stButton > button:hover {{
    border-color: {ACCENT};
    color: {ACCENT};
    box-shadow: 0 0 0 3px rgba(0,212,170,0.12);
}}
.stButton > button[kind="primary"] {{
    background: linear-gradient(135deg, {ACCENT} 0%, #00b893 100%);
    color: #062019;
    border: none;
    font-weight: 700;
}}

/* ---------- Dataframes ---------- */
[data-testid="stDataFrame"] {{
    border: 1px solid {BORDER};
    border-radius: 10px;
    overflow: hidden;
}}

/* ---------- Headers / dividers ---------- */
h1, h2, h3, h4 {{ color: {TEXT}; }}
h2 {{ border-bottom: 1px solid {BORDER}; padding-bottom: 6px; }}
hr {{ border-color: {BORDER}; opacity: 0.6; }}

/* ---------- Alerts (st.warning/info/success) get a softer card look ---------- */
[data-testid="stAlert"] {{
    border-radius: 10px;
    border: 1px solid {BORDER};
}}

/* ---------- Discovery chip cards ---------- */
.disc-chip {{
    background: {CARD};
    border: 1px solid {BORDER};
    border-radius: 10px;
    padding: 10px 12px;
    transition: border-color .15s ease, transform .15s ease;
}}
.disc-chip:hover {{ border-color: {ACCENT}; transform: translateY(-1px); }}

/* ---------- Inputs ---------- */
[data-baseweb="select"] > div, [data-baseweb="input"] > div {{
    background-color: {CARD} !important;
    border-color: {BORDER} !important;
}}

/* ---------- Loading indicator ---------- */
@keyframes dk-spin {{ to {{ transform: rotate(360deg); }} }}
@keyframes dk-pulse {{ 0%,100% {{ opacity: 0.55; }} 50% {{ opacity: 1; }} }}
@keyframes dk-shimmer {{ 0% {{ background-position: -400px 0; }} 100% {{ background-position: 400px 0; }} }}

.dk-loader {{
    display: flex; align-items: center; gap: 16px;
    background: linear-gradient(135deg, rgba(0,212,170,0.12), rgba(78,161,255,0.08));
    border: 1px solid {ACCENT};
    border-radius: 12px;
    padding: 16px 20px;
    margin: 6px 0 16px 0;
    animation: dk-pulse 1.6s ease-in-out infinite;
    box-shadow: 0 4px 24px rgba(0,212,170,0.18);
}}
.dk-spinner {{
    width: 30px; height: 30px; flex: 0 0 30px;
    border-radius: 50%;
    border: 3px solid rgba(0,212,170,0.2);
    border-top-color: {ACCENT};
    border-right-color: {ACCENT_2};
    animation: dk-spin 0.8s linear infinite;
}}
.dk-loader-text {{ color: {TEXT}; font-weight: 700; font-size: 15px; }}
.dk-loader-sub {{ color: {TEXT_DIM}; font-size: 12px; margin-top: 2px; }}

.dk-shimmer-bar {{
    height: 6px; border-radius: 3px; margin-top: 10px;
    background: linear-gradient(90deg, {CARD} 0%, {ACCENT} 50%, {CARD} 100%);
    background-size: 400px 100%;
    animation: dk-shimmer 1.2s linear infinite;
}}
</style>
"""


def _light_override() -> str:
    """Additive CSS that flips the main surfaces to light mode."""
    return f"""
<style>
.stApp {{
    background:
      radial-gradient(1100px 600px at 8% -10%, rgba(0,212,170,0.05), transparent 60%),
      radial-gradient(900px 500px at 95% 0%, rgba(78,161,255,0.06), transparent 55%),
      linear-gradient(180deg, {_LIGHT['BG']} 0%, #e9eef6 100%) !important;
    color: {_LIGHT['TEXT']} !important;
}}
[data-testid="stSidebar"] {{
    background: linear-gradient(180deg, #ffffff 0%, #eef2fa 100%) !important;
    border-right: 1px solid {_LIGHT['BORDER']} !important;
}}
.dk-toolbar, .kpi, .dk-brand, .disc-chip {{
    background: {_LIGHT['CARD']} !important;
    border-color: {_LIGHT['BORDER']} !important;
    box-shadow: 0 2px 10px rgba(20,30,60,0.06) !important;
}}
.kpi-value {{ color: {_LIGHT['TEXT']}; }}
.dk-brand-title, h1, h2, h3, h4 {{ color: {_LIGHT['TEXT']} !important; }}
.kpi-label, .kpi-sub, .dk-brand-sub, .dk-brand-clock, .sidebar-section-title {{
    color: {_LIGHT['TEXT_DIM']} !important;
}}
.stTabs [aria-selected="true"] {{
    background: {_LIGHT['CARD']} !important;
    border-color: {_LIGHT['BORDER']} !important;
    border-bottom-color: {_LIGHT['CARD']} !important;
}}
.stTabs [data-baseweb="tab"] {{ color: {_LIGHT['TEXT_DIM']}; }}
.stButton > button {{ background: {_LIGHT['CARD']}; color: {_LIGHT['TEXT']};
                      border-color: {_LIGHT['BORDER']}; }}
[data-testid="stDataFrame"] {{ border-color: {_LIGHT['BORDER']}; }}
[data-baseweb="select"] > div, [data-baseweb="input"] > div {{
    background-color: {_LIGHT['CARD']} !important;
    border-color: {_LIGHT['BORDER']} !important;
}}
hr {{ border-color: {_LIGHT['BORDER']}; }}
/* DK footer */
.dk-footer {{
    margin-top: 38px; padding: 18px 0 8px 0;
    border-top: 1px solid {_LIGHT['BORDER']};
    text-align: center; color: {_LIGHT['TEXT_DIM']};
}}
</style>
"""


def inject(mode: str = "dark"):
    set_mode(mode)
    st.markdown(CSS, unsafe_allow_html=True)   # dark base always present
    if mode == "light":
        st.markdown(_light_override(), unsafe_allow_html=True)


def footer(signature: str = "DK Investing™") -> None:
    """Render the trademark footer signature at the bottom of the page."""
    st.markdown(
        f"<div class='dk-footer' style='margin-top:38px;padding:18px 0 8px 0;"
        f"border-top:1px solid {BORDER};text-align:center;color:{TEXT_DIM};'>"
        f"<div style='font-weight:700;letter-spacing:0.5px;color:{ACCENT};'>{signature}</div>"
        f"<div style='font-size:11px;margin-top:4px;'>"
        f"For research and educational purposes only — not investment advice. "
        f"Data may be delayed.</div>"
        f"</div>",
        unsafe_allow_html=True,
    )


def loading_banner(text: str = "Loading fresh market data…",
                   sub: str = "Pulling prices, news, sentiment, themes and alerts. This takes ~30–45 seconds.") -> str:
    """Animated loading indicator (spinner + pulsing card + shimmer bar)."""
    return (
        '<div class="dk-loader">'
        '  <div class="dk-spinner"></div>'
        '  <div style="flex:1;">'
        f'    <div class="dk-loader-text">{text}</div>'
        f'    <div class="dk-loader-sub">{sub}</div>'
        '    <div class="dk-shimmer-bar"></div>'
        '  </div>'
        '</div>'
    )


# ---------- Plotly theme ----------
PLOTLY_LAYOUT = dict(
    paper_bgcolor=CARD,
    plot_bgcolor=CARD,
    font=dict(color=TEXT, family="Inter, system-ui, sans-serif", size=12),
    xaxis=dict(
        gridcolor="rgba(255,255,255,0.05)",
        zerolinecolor="rgba(255,255,255,0.10)",
        linecolor=BORDER,
        tickcolor=BORDER,
    ),
    yaxis=dict(
        gridcolor="rgba(255,255,255,0.05)",
        zerolinecolor="rgba(255,255,255,0.10)",
        linecolor=BORDER,
        tickcolor=BORDER,
    ),
    hoverlabel=dict(bgcolor=CARD, bordercolor=ACCENT, font=dict(color=TEXT)),
    legend=dict(bgcolor="rgba(0,0,0,0)", bordercolor=BORDER, borderwidth=1),
    margin=dict(l=8, r=8, t=24, b=8),
)

CANDLE_COLORS = dict(
    increasing_line_color=BULL, increasing_fillcolor=BULL,
    decreasing_line_color=BEAR, decreasing_fillcolor=BEAR,
)

LINE_PRIMARY = dict(color=ACCENT, width=2.4)
LINE_MA20 = dict(color=ACCENT_2, width=1.4)
LINE_MA50 = dict(color="#b66dff", width=1.4)
LINE_MA200 = dict(color="#ffb547", width=1.4, dash="dash")


def _live_plotly_layout() -> dict:
    """Plotly layout built from CURRENT palette globals (mode-aware)."""
    grid = "rgba(0,0,0,0.06)" if MODE == "light" else "rgba(255,255,255,0.05)"
    zero = "rgba(0,0,0,0.12)" if MODE == "light" else "rgba(255,255,255,0.10)"
    return dict(
        paper_bgcolor=CARD, plot_bgcolor=CARD,
        font=dict(color=TEXT, family="Inter, system-ui, sans-serif", size=12),
        xaxis=dict(gridcolor=grid, zerolinecolor=zero, linecolor=BORDER, tickcolor=BORDER),
        yaxis=dict(gridcolor=grid, zerolinecolor=zero, linecolor=BORDER, tickcolor=BORDER),
        hoverlabel=dict(bgcolor=CARD, bordercolor=ACCENT, font=dict(color=TEXT)),
        legend=dict(bgcolor="rgba(0,0,0,0)", bordercolor=BORDER, borderwidth=1),
        margin=dict(l=8, r=8, t=24, b=8),
    )


def style_fig(fig, height: int = 360):
    fig.update_layout(**_live_plotly_layout(), height=height,
                      xaxis_rangeslider_visible=False)
    return fig


def kpi_card(label: str, value: str, sub: str = "", flavor: str = "") -> str:
    cls = f"kpi {flavor}" if flavor else "kpi"
    return (
        f'<div class="{cls}">'
        f'  <div class="kpi-label">{label}</div>'
        f'  <div class="kpi-value">{value}</div>'
        f'  <div class="kpi-sub">{sub}</div>'
        f'</div>'
    )


def brand_bar(title: str = "DK Investing", subtitle: str = "Sentiment + opportunity engine",
              right: str = "") -> str:
    return (
        '<div class="dk-brand">'
        '  <div class="dk-brand-left">'
        '    <div class="dk-brand-logo">DK</div>'
        '    <div>'
       f'      <div class="dk-brand-title">{title}</div>'
       f'      <div class="dk-brand-sub">{subtitle}</div>'
        '    </div>'
        '  </div>'
       f'  <div class="dk-brand-clock">{right}</div>'
        '</div>'
    )


def sidebar_section(title: str):
    st.sidebar.markdown(f'<div class="sidebar-section-title">{title}</div>',
                        unsafe_allow_html=True)
