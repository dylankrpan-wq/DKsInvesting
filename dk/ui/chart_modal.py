"""Reusable chart-preview popup. Triggered by row clicks in tables.

Uses st.dialog (Streamlit 1.34+) for a true modal with chart + key stats.
"""
from __future__ import annotations
import sqlite3
import pandas as pd
import streamlit as st
from dk.config import DB_PATH
from dk.indicators import ta as ta_mod
from dk.ui import style as ui_style


@st.dialog("Chart preview", width="large")
def show_chart_for(symbol: str) -> None:
    """Render a popup with chart + indicator snapshot for `symbol`."""
    if not symbol:
        st.error("No symbol provided.")
        return

    # Explicit close button — sets the closed flag for ALL clickable tables.
    # (We can't tie it to a specific key here, so set every known closed_key
    # to True. Cheap and effective.)
    close_col1, close_col2 = st.columns([6, 1])
    with close_col2:
        if st.button("✕ Close", key=f"close_{symbol}", help="Close this chart preview"):
            # Mark every clickable_table's modal as closed for this session
            for k in list(st.session_state.keys()):
                if k.startswith("_dk_modal_closed__"):
                    st.session_state[k] = True
            st.rerun()

    _loading = st.empty()
    _loading.info(f":hourglass_flowing_sand: Loading chart for **{symbol}**...")

    # Try equity prices first; fall back to crypto if no equity bars exist.
    with sqlite3.connect(DB_PATH) as c:
        eq = pd.read_sql_query(
            "SELECT ts, open, high, low, close, volume FROM prices WHERE symbol=? "
            "ORDER BY ts DESC LIMIT 90",
            c, params=(symbol,),
        )
        cr = pd.read_sql_query(
            "SELECT ts, price_usd, change_24h_pct, vol_24h, market_cap "
            "FROM crypto_prices WHERE symbol=? ORDER BY ts DESC LIMIT 60",
            c, params=(symbol,),
        )
        opp = pd.read_sql_query(
            """SELECT score, direction, sentiment, price_mom FROM score_history
               WHERE symbol=? ORDER BY snapshot_ts DESC LIMIT 1""",
            c, params=(symbol,),
        )
        tv = pd.read_sql_query(
            "SELECT recommendation, buy_signals, sell_signals, neutral_signals "
            "FROM tv_ratings WHERE symbol=? AND interval='1d' LIMIT 1",
            c, params=(symbol,),
        )
        nxt = pd.read_sql_query(
            "SELECT report_date FROM earnings WHERE symbol=? AND report_date >= date('now') "
            "ORDER BY report_date ASC LIMIT 1",
            c, params=(symbol,),
        )

    _loading.empty()
    st.markdown(f"### {symbol}")

    # ---- Stat cards ----
    c1, c2, c3, c4 = st.columns(4)

    if not eq.empty:
        last = float(eq.iloc[0]["close"])
        prev = float(eq.iloc[1]["close"]) if len(eq) > 1 else last
        chg_pct = (last - prev) / prev * 100 if prev else 0.0
        c1.metric("Last close", f"${last:,.2f}", f"{chg_pct:+.2f}%")
    elif not cr.empty:
        last = float(cr.iloc[0]["price_usd"]) if cr.iloc[0]["price_usd"] else 0
        chg = float(cr.iloc[0]["change_24h_pct"]) if cr.iloc[0]["change_24h_pct"] else 0
        c1.metric("Price (USD)", f"${last:,.2f}", f"{chg:+.2f}% 24h")
    else:
        c1.metric("Last price", "—")

    if not opp.empty:
        c2.metric("DK score", f"{opp.iloc[0]['score']:.1f}", opp.iloc[0]['direction'])
    else:
        c2.metric("DK score", "—")

    if not tv.empty:
        rec = tv.iloc[0]["recommendation"] or "—"
        sub = f"{int(tv.iloc[0]['buy_signals'] or 0)}B / {int(tv.iloc[0]['sell_signals'] or 0)}S"
        c3.metric("TV rating", rec.replace("_", " "), sub)
    else:
        c3.metric("TV rating", "—")

    if not nxt.empty:
        c4.metric("Next earnings", str(nxt.iloc[0]["report_date"])[:10])
    else:
        c4.metric("Next earnings", "—")

    # ---- Chart studio (full controls inside the modal) ----
    if not eq.empty:
        from dk.ui import chart_studio
        chart_studio.render(symbol, key=f"modal_{symbol}", default_period="3M")
    elif not cr.empty:
        import plotly.graph_objects as go
        cr_sorted = cr.sort_values("ts")
        fig = go.Figure(go.Scatter(
            x=cr_sorted["ts"], y=cr_sorted["price_usd"],
            mode="lines+markers", name="price",
            line=ui_style.LINE_PRIMARY,
            fill="tozeroy", fillcolor="rgba(0,212,170,0.10)",
        ))
        ui_style.style_fig(fig, height=300)
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info(f"No price history yet for {symbol}. Click **Refresh data** to backfill.")

    # ---- TA notes ----
    try:
        snap = ta_mod.compute(symbol)
        if snap.setup_notes:
            st.markdown("**Setup notes**")
            for n in snap.setup_notes:
                st.markdown(f"- {n}")
    except Exception:
        pass

    # Research links — dive into the underlying data / sources
    try:
        from dk.util import links as _lk
        rs = _lk.research_set(symbol)
        st.markdown("**🔗 Research & sources**")
        st.markdown(" · ".join(f"[{label}]({url})" for label, url in rs.items()))
    except Exception:
        pass

    st.caption(":bulb: For the full breakdown, switch to the **Thesis** tab and pick this symbol.")


def clickable_table(df: pd.DataFrame, *, key: str, symbol_col: str = "symbol",
                    column_config: dict | None = None) -> None:
    """Render a dataframe whose rows pop a chart modal on click.

    The modal persists across reruns triggered by widgets INSIDE it
    (e.g. changing the chart timeframe). User closes via the X button.
    """
    state_key = f"_dk_modal_sym__{key}"
    closed_key = f"_dk_modal_closed__{key}"

    event = st.dataframe(
        df,
        use_container_width=True, hide_index=True,
        on_select="rerun", selection_mode="single-row",
        column_config=column_config,
        key=key,
    )

    # Detect a fresh row selection
    new_sym = None
    if event and getattr(event, "selection", None) and event.selection.rows:
        idx = event.selection.rows[0]
        cand = df.iloc[idx][symbol_col]
        if isinstance(cand, str) and cand:
            new_sym = cand

    current_sym = st.session_state.get(state_key)

    # New row selected → open dialog with that symbol, clear any prior 'closed' flag
    if new_sym and new_sym != current_sym:
        st.session_state[state_key] = new_sym
        st.session_state[closed_key] = False
        show_chart_for(new_sym)
    elif new_sym and new_sym == current_sym and not st.session_state.get(closed_key, False):
        # Same symbol still selected → keep re-opening dialog through reruns
        show_chart_for(current_sym)
