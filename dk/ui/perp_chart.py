"""Live perp chart for the dashboard — Blofin candles with the computed setup
drawn on top.

Thin Streamlit wrapper around dk.charts.perp_fig (the figure assembly + setup
overlay live there, Streamlit-free, so the Telegram push can reuse them). This
module only adds the controls, caching, and the stat strip.

Discovery, not instructions: both the long and short framings are available;
every level is measured from live data, never fabricated. Never places a trade.
"""
from __future__ import annotations
import streamlit as st
from dk.analysis import perp
from dk.charts import perp_fig

TIMEFRAME_KEYS = perp_fig.TIMEFRAME_KEYS


@st.cache_data(ttl=120, show_spinner=False)
def _candles_df(inst_id: str, timeframe: str):
    return perp_fig.fetch_df(inst_id, timeframe)


@st.cache_data(ttl=120, show_spinner=False)
def _analysis(inst_id: str) -> dict | None:
    """Cached structure read so changing timeframe/overlay doesn't re-hit the API."""
    return perp.analyze(inst_id)


def render(pair: str, key: str = "perp_chart") -> None:
    """Render the live perp chart + overlay for `pair` into the current container."""
    inst_id = perp_fig.norm_pair(pair)
    if not inst_id:
        st.info("Type a perp (e.g. BTC-USDT or just BTC) to chart it.")
        return

    # ---- Controls ----
    c1, c2, c3 = st.columns([2.2, 1.6, 1.4])
    timeframe = c1.radio("Timeframe", TIMEFRAME_KEYS, index=TIMEFRAME_KEYS.index("1H"),
                         horizontal=True, key=f"{key}_tf")
    overlay = c2.radio("Setup overlay", ["Long", "Short", "Both", "None"],
                       index=0, horizontal=True, key=f"{key}_ov")
    lower = c3.selectbox("Lower panel", ["RSI", "MACD", "None"], index=0, key=f"{key}_lower")

    o = st.columns(5)
    show_ma20 = o[0].checkbox("MA20", value=True, key=f"{key}_ma20")
    show_ma50 = o[1].checkbox("MA50", value=True, key=f"{key}_ma50")
    show_ema = o[2].checkbox("EMA 12/26", value=False, key=f"{key}_ema")
    show_bb = o[3].checkbox("Bollinger", value=False, key=f"{key}_bb")
    show_vol = o[4].checkbox("Volume", value=True, key=f"{key}_vol")

    with st.spinner(f"Fetching {inst_id} {timeframe} candles from Blofin…"):
        df = _candles_df(inst_id, timeframe)
    if df.empty:
        st.warning(f"No Blofin perp candles for **{inst_id}** at {timeframe}. "
                   "Check the symbol (e.g. BTC-USDT).")
        return

    a = _analysis(inst_id)  # setup levels + funding/structure (may be None)
    fig = perp_fig.build_figure(
        inst_id, df, a, timeframe=timeframe, overlay=overlay, lower=lower,
        show_vol=show_vol, show_ma20=show_ma20, show_ma50=show_ma50,
        show_ema=show_ema, show_bb=show_bb,
    )
    st.plotly_chart(fig, use_container_width=True, key=f"{key}_fig")

    # ---- Stat strip under the chart ----
    if a:
        m = st.columns(4)
        m[0].metric("Last", f"${perp._fmt(a.get('last'))}",
                    f"{a.get('chg_24h_pct'):+}% 24h" if a.get("chg_24h_pct") is not None else None)
        fp = a.get("funding_pct")
        m[1].metric("Funding", f"{fp:+}%" if fp is not None else "—", a.get("funding_side") or None)
        m[2].metric("Phase", a.get("phase", "—"))
        m[3].metric("Micro", a.get("micro_pos", "—"))
        st.caption(f"As of {a.get('as_of_utc','')} UTC · live Blofin ticker/candles/funding. "
                   "Lines are the measured defined-risk setup (entry · stop · TP1/2/3, *=R-mult). "
                   "No order-book/OI/IV — discovery, not a trade instruction.")
    else:
        st.caption(f"{inst_id} candles shown; structure read unavailable (overlay off).")
