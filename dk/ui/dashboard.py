"""Streamlit dashboard. Launch:
    uv run streamlit run dk/ui/dashboard.py
"""
from __future__ import annotations
import sys
from pathlib import Path
# Make the project root importable regardless of how Streamlit was launched.
_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import sqlite3
import pandas as pd
import streamlit as st
from dk.config import (
    load_watchlist, DB_PATH,
    add_to_watchlist, remove_from_watchlist, is_user_added,
)
from dk.store import db as store
from dk.jobs import poller
from dk.sentiment.scorer import label as senti_label
from dk.opportunity import score as opp_score
from dk.opportunity import delta as opp_delta
from dk.discovery import scanner as discovery
from dk.thesis import generator as thesis_gen
from dk.indicators import ta as ta_mod
from dk.brokers import all_configured as configured_brokers
from dk.brokers import sync as broker_sync
from dk.brokers import ALL_BROKERS as _ALL_BROKER_CLASSES
from dk.config import _load_user_additions as _load_user_additions_fn
from dk.ui import style as ui_style
from dk.ui.chart_modal import clickable_table
from dk.ui import chart_studio
from dk.ui import glossary as ui_glossary
from dk.notes import journal as notes_mod
from dk.themes import registry as themes_reg
from dk.digest import daily as digest_mod

# Page config is set by streamlit_app.py (the Cloud entry point) so it runs before any other
# st.* call. We avoid calling it here since duplicate calls raise an error.
try:
    st.set_page_config(
        page_title="DK Investing",
        layout="wide",
        page_icon=":chart_with_upwards_trend:",
        initial_sidebar_state="collapsed",
    )
except st.errors.StreamlitAPIException:
    pass  # already set by entry point — fine

ui_style.inject()
store.init_db()

# ---- Deferred refresh handler ----
# Long-running poller blocks the render thread, so we run it on a dedicated
# pass with ONLY the status panel visible, then rerun to repaint the full
# dashboard with fresh data. No more half-rendered/blank intermediate screen.
if st.session_state.get("_dk_refresh_pending"):
    st.session_state.pop("_dk_refresh_pending", None)
    st.markdown(ui_style.brand_bar(right="refreshing..."), unsafe_allow_html=True)
    with st.status(":arrows_counterclockwise: Refreshing DK data... please wait ~30-45 seconds",
                   expanded=True) as _status:
        st.write(":chart_with_upwards_trend: Pulling prices + earnings...")
        st.write(":newspaper: Fetching news from RSS feeds + per-ticker Yahoo...")
        st.write(":coin: Pulling crypto snapshots...")
        st.write(":calendar: Loading macro calendar + IPO pipeline...")
        st.write(":robot_face: Fetching TradingView technical ratings...")
        st.write(":telescope: Running discovery scanner + Reddit trending...")
        st.write(":rocket: Scoring 15 themes...")
        st.write(":mag: Computing sentiment + opportunity scores...")
        st.write(":lock: Syncing connected brokers...")
        st.write(":rotating_light: Running alert engine...")
        try:
            summary = poller.run_once()
            st.session_state["_dk_last_summary"] = summary
            _status.update(label=":white_check_mark: Refresh complete!",
                            state="complete", expanded=False)
        except Exception as e:
            import traceback
            _status.update(label=f":x: Refresh failed: {e}", state="error", expanded=True)
            st.error(f"**{type(e).__name__}**: {e}")
            st.code(traceback.format_exc(), language="python")
            st.stop()
    st.rerun()


def q(sql: str, params: tuple = ()) -> pd.DataFrame:
    with sqlite3.connect(DB_PATH) as c:
        return pd.read_sql_query(sql, c, params=params)


# ---- Live alert count ----
unseen = q("SELECT COUNT(*) AS n FROM alerts WHERE seen=0").iloc[0]["n"]

# ---- Owned symbols (for OWNED badging) ----
owned_df = q("SELECT DISTINCT UPPER(symbol) AS sym FROM positions WHERE quantity > 0")
OWNED = set(owned_df["sym"].tolist()) if not owned_df.empty else set()


def owned_badge(sym: str | None) -> str:
    if sym and sym.upper() in OWNED:
        return " :green-background[OWNED]"
    return ""


# ---- Brand bar + KPI strip ----
from datetime import datetime, timezone
_now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

# Top opportunity, biggest mover, next macro event for the KPI strip
_top_opp = q("""
    SELECT symbol, score, direction FROM score_history
    WHERE snapshot_ts = (SELECT MAX(snapshot_ts) FROM score_history)
    ORDER BY score DESC LIMIT 1
""")
_biggest_chg = q("""
    SELECT symbol, score, score_chg FROM (
        SELECT cur.symbol, cur.score,
               (cur.score - prv.score) AS score_chg
        FROM score_history cur
        JOIN score_history prv ON prv.symbol = cur.symbol
        WHERE cur.snapshot_ts = (SELECT MAX(snapshot_ts) FROM score_history)
          AND prv.snapshot_ts = (SELECT MAX(snapshot_ts) FROM score_history
                                  WHERE snapshot_ts < (SELECT MAX(snapshot_ts) FROM score_history))
    ) ORDER BY ABS(score_chg) DESC LIMIT 1
""")
_next_macro = q("""SELECT event_date, title FROM macro_events
                   WHERE event_date >= date('now') AND importance >= 2
                   ORDER BY event_date ASC LIMIT 1""")

_top_opp_html = (
    f"{_top_opp.iloc[0]['symbol']} · {_top_opp.iloc[0]['score']:.1f}"
    if not _top_opp.empty else "—"
)
_top_opp_sub = _top_opp.iloc[0]["direction"] if not _top_opp.empty else "no data"

if not _biggest_chg.empty:
    sc = _biggest_chg.iloc[0]["score_chg"]
    flavor = "bull" if sc > 0 else "bear"
    _mover_html = f"{_biggest_chg.iloc[0]['symbol']} {sc:+.1f}"
    _mover_sub = "vs prior snapshot"
else:
    flavor = ""
    _mover_html = "—"
    _mover_sub = "Need 2+ snapshots"

_macro_html = _next_macro.iloc[0]["title"][:28] if not _next_macro.empty else "—"
_macro_sub = _next_macro.iloc[0]["event_date"] if not _next_macro.empty else ""

_alerts_flavor = "warn" if unseen else ""

st.markdown(ui_style.brand_bar(right=_now_utc), unsafe_allow_html=True)
st.markdown(
    '<div class="kpi-grid">'
    + ui_style.kpi_card("Unseen alerts", str(unseen),
                        "click Alerts tab" if unseen else "all clear",
                        flavor=_alerts_flavor)
    + ui_style.kpi_card("Top opportunity", _top_opp_html, _top_opp_sub, flavor="bull")
    + ui_style.kpi_card("Biggest mover", _mover_html, _mover_sub, flavor=flavor)
    + ui_style.kpi_card("Next macro event", _macro_html, _macro_sub)
    + '</div>',
    unsafe_allow_html=True,
)

# ---- Macro context strip (VIX, DXY, 10Y, oil, gold, SPX) ----
macro_ctx = q("SELECT symbol, label, last_value, chg_pct FROM macro_context ORDER BY symbol")
if not macro_ctx.empty:
    cards_html = ['<div class="kpi-grid" style="grid-template-columns:repeat(6,1fr);">']
    for _, m in macro_ctx.iterrows():
        chg = m["chg_pct"] or 0
        flavor = "bull" if chg > 0 else ("bear" if chg < 0 else "")
        sub = f"{chg:+.2f}%"
        val = m["last_value"] or 0
        if m["symbol"] == "US10Y":
            value_str = f"{val:.2f}%"
        elif m["symbol"] in {"VIX"}:
            value_str = f"{val:.2f}"
        else:
            value_str = f"{val:,.2f}"
        cards_html.append(ui_style.kpi_card(m["label"], value_str, sub, flavor=flavor))
    cards_html.append('</div>')
    st.markdown("".join(cards_html), unsafe_allow_html=True)

# ---- Top filter toolbar (replaces sidebar filters) ----
wl = load_watchlist()
all_regions = wl.get("regions", ["US", "EU", "ASIA", "GLOBAL"])
equity_syms = [e["symbol"] for e in (wl.get("equities") or []) + (wl.get("etfs") or [])]
senti_engine = (wl.get("sentiment") or {}).get("engine", "vader")

st.markdown('<div class="dk-toolbar">', unsafe_allow_html=True)
tb_col1, tb_col2, tb_col3, tb_col4, tb_col5 = st.columns([1.4, 1.2, 2.0, 1.4, 1.0])

with tb_col1:
    refresh_clicked = st.button("⟳  Refresh data", type="primary", use_container_width=True)

with tb_col2:
    mark_seen_clicked = st.button("✓  Mark alerts seen", use_container_width=True)

with tb_col3:
    selected_regions = st.multiselect(
        "Regions", all_regions, default=all_regions,
        label_visibility="collapsed", placeholder="Select news regions",
    )

with tb_col4:
    focus = st.selectbox(
        "Focus ticker", ["(all)"] + equity_syms,
        label_visibility="collapsed",
    )

with tb_col5:
    st.markdown(
        f"<div style='text-align:right; padding-top:6px;'>"
        f"<span style='color:#8b95ad;font-size:11px;'>ENGINE</span> "
        f"<code style='color:#00d4aa;'>{senti_engine}</code>"
        f"</div>",
        unsafe_allow_html=True,
    )

st.markdown('</div>', unsafe_allow_html=True)

# Handle toolbar actions
if refresh_clicked:
    # Set a flag and rerun. The deferred handler at the top of the script
    # picks this up and runs the poller on its own clean render pass.
    st.session_state["_dk_refresh_pending"] = True
    st.rerun()

# Show the last run summary (after a refresh completes)
_last_summary = st.session_state.get("_dk_last_summary")
if _last_summary:
    with st.expander(":white_check_mark: Last refresh — run summary", expanded=False):
        st.json(_last_summary)

if mark_seen_clicked:
    with sqlite3.connect(DB_PATH) as c:
        c.execute("UPDATE alerts SET seen=1")
        c.commit()
    st.rerun()

# ---- Left sidebar: Key & Glossary popout drawer ----
# Click the « arrow at top-left of the page to expand. Click again to collapse to a thin tab.
ui_glossary.render_sidebar_glossary()

(tab_opps, tab_thesis, tab_themes, tab_charts, tab_discover, tab_tools,
 tab_alerts, tab_watch, tab_portfolio, tab_sentiment, tab_news, tab_earnings,
 tab_calendar, tab_crypto) = st.tabs(
    ["Opportunities", "Thesis", "Themes", "Charts", "Discover", "Tools",
     f"Alerts ({unseen})", "Watchlist", "Portfolio", "Sentiment", "News",
     "Earnings", "Calendar", "Crypto"]
)

with tab_themes:
    st.subheader("Theme packs")
    st.caption("Curated thematic baskets — like Schwab Theme Packs. Each shows aggregate "
               "DK score, sentiment, and 1-day move across constituents, plus the **why**.")
    if st.button("Refresh theme scores (incl. on-demand price fetch)", key="themes_refresh"):
        with st.spinner(":satellite: Fetching prices for non-watchlist constituents and rescoring 15 themes..."):
            themes_reg.score_all(fetch_missing=True)
        st.success("Themes refreshed")
        st.rerun()

    @st.cache_data(ttl=60, show_spinner="Scoring themes...")
    def _cached_score_all():
        return themes_reg.score_all(fetch_missing=False)

    scored = _cached_score_all()
    if not scored:
        st.info("No themes scored yet. Click the refresh button above.")
    else:
        # Theme cards grid
        df_th = pd.DataFrame([{
            "id": t["id"], "name": t["name"], "category": t.get("category", "?"),
            "score": t["aggregate_score"], "sentiment": t.get("avg_sentiment", 0),
            "1d %": t.get("avg_price_chg_1d", 0), "n": t.get("constituent_count", 0),
            "leader": t.get("top_contributor", ""),
        } for t in scored])
        st.dataframe(
            df_th, use_container_width=True, hide_index=True,
            column_config={
                "score": st.column_config.ProgressColumn(
                    "agg score", min_value=0, max_value=100, format="%.1f"),
                "sentiment": st.column_config.NumberColumn("sentiment", format="%+.2f"),
                "1d %": st.column_config.NumberColumn("1d %", format="%+.2f%%"),
            },
        )

        st.markdown("---")
        st.markdown("#### Drill into a theme")
        theme_choice = st.selectbox(
            "Theme",
            [t["name"] for t in scored],
            key="theme_drill",
        )
        sel = next(t for t in scored if t["name"] == theme_choice)

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Aggregate score", f"{sel['aggregate_score']:.1f}")
        c2.metric("Avg sentiment", f"{sel.get('avg_sentiment', 0):+.2f}")
        c3.metric("Avg 1d %", f"{sel.get('avg_price_chg_1d', 0):+.2f}%")
        c4.metric("Top contributor", sel.get("top_contributor") or "—")

        st.markdown(f"**{sel['name']}** — *{sel.get('description', '')}*")

        # Constituents table
        cs = pd.DataFrame(sel.get("constituents_scored", []))
        if not cs.empty:
            cs = cs.rename(columns={"price_chg_1d": "1d %"})
            clickable_table(
                cs.round({"score": 1, "sentiment": 3, "sentiment_24h": 3, "1d %": 2}),
                key=f"theme_consts_{sel['id']}",
                column_config={
                    "score": st.column_config.ProgressColumn(
                        "score", min_value=0, max_value=100, format="%.1f"),
                    "1d %": st.column_config.NumberColumn("1d %", format="%+.2f%%"),
                    "sentiment": st.column_config.NumberColumn("sentiment", format="%+.2f"),
                    "sentiment_24h": st.column_config.NumberColumn("sent 24h", format="%+.2f"),
                },
            )
            st.caption(":bulb: Click any constituent for the chart preview.")

        # The "why" — recent catalyst news across constituents
        st.markdown("##### Why is this theme moving — recent catalysts")
        news = themes_reg.theme_news(sel, limit=8)
        if not news:
            st.caption("No recent strong-sentiment news for this theme's constituents.")
        else:
            for n in news:
                tone = ":green[+]" if (n.get("sentiment") or 0) > 0.05 else (
                    ":red[−]" if (n.get("sentiment") or 0) < -0.05 else "·"
                )
                st.markdown(
                    f"- {tone} `{n['symbol']}` **[{n['title']}]({n['url']})**  \n"
                    f"  <small>{n['source']} · {n['published']} · score {n['sentiment']:+.2f}</small>",
                    unsafe_allow_html=True,
                )

with tab_tools:
    st.subheader("Tools")
    tools_choice = st.radio(
        "Tool", ["Heatmap", "Compare tickers", "Position sizing", "Custom alerts"],
        horizontal=True, label_visibility="collapsed", key="tools_choice",
    )

    # ===== HEATMAP =====
    if tools_choice == "Heatmap":
        st.markdown("#### Watchlist heatmap")
        st.caption("Cells sized by latest dollar volume, colored by daily % change. "
                   "Click any tile to pop the chart preview.")
        hm_df = q("""
            SELECT p.symbol, p.close, p.volume,
              (SELECT close FROM prices p2
               WHERE p2.symbol=p.symbol AND p2.ts < p.ts
               ORDER BY p2.ts DESC LIMIT 1) AS prior_close
            FROM prices p
            INNER JOIN (SELECT symbol, MAX(ts) m FROM prices GROUP BY symbol) lat
              ON p.symbol=lat.symbol AND p.ts=lat.m
        """)
        if hm_df.empty:
            st.info("No price data yet.")
        else:
            hm_df = hm_df.dropna(subset=["close", "prior_close"])
            hm_df["chg_pct"] = (hm_df["close"] - hm_df["prior_close"]) / hm_df["prior_close"] * 100
            hm_df["dollar_vol"] = hm_df["close"] * hm_df["volume"]
            hm_df["size"] = hm_df["dollar_vol"].fillna(hm_df["dollar_vol"].mean())
            hm_df["label"] = hm_df.apply(
                lambda r: f"{r['symbol']}<br>{r['chg_pct']:+.2f}%", axis=1)
            import plotly.express as px
            fig = px.treemap(
                hm_df, path=["symbol"], values="size",
                color="chg_pct",
                color_continuous_scale=[
                    [0.0, ui_style.BEAR],
                    [0.5, "#1c2440"],
                    [1.0, ui_style.BULL],
                ],
                color_continuous_midpoint=0,
                custom_data=["chg_pct", "close"],
            )
            fig.update_traces(
                textfont=dict(size=16, color=ui_style.TEXT, family="Inter"),
                texttemplate="<b>%{label}</b><br>%{customdata[0]:+.2f}%<br>$%{customdata[1]:,.2f}",
                hovertemplate="<b>%{label}</b><br>chg %{customdata[0]:+.2f}%<br>close $%{customdata[1]:,.2f}<extra></extra>",
                marker=dict(line=dict(color=ui_style.BORDER, width=2)),
            )
            ui_style.style_fig(fig, height=560)
            fig.update_layout(coloraxis_showscale=False)
            st.plotly_chart(fig, use_container_width=True)

    # ===== COMPARE =====
    elif tools_choice == "Compare tickers":
        st.markdown("#### Compare tickers")
        st.caption("Pick 2–5 tickers to overlay normalized performance and see correlation.")
        cmp_syms = st.multiselect(
            "Select 2–5 tickers", equity_syms,
            default=equity_syms[:3] if len(equity_syms) >= 3 else equity_syms,
            max_selections=5, key="compare_syms",
        )
        if len(cmp_syms) < 2:
            st.info("Select at least 2 tickers.")
        else:
            placeholders = ",".join("?" * len(cmp_syms))
            cmp_df = q(
                f"SELECT symbol, ts, close FROM prices WHERE symbol IN ({placeholders}) ORDER BY ts ASC",
                tuple(cmp_syms),
            )
            if cmp_df.empty:
                st.info("No price data for the selected symbols.")
            else:
                pivot = cmp_df.pivot(index="ts", columns="symbol", values="close").dropna()
                normalized = (pivot / pivot.iloc[0] - 1) * 100  # % change vs first bar
                import plotly.graph_objects as go
                fig = go.Figure()
                palette = [ui_style.ACCENT, ui_style.ACCENT_2, "#b66dff",
                           ui_style.WARN, ui_style.BEAR]
                for i, sym in enumerate(normalized.columns):
                    fig.add_trace(go.Scatter(
                        x=normalized.index, y=normalized[sym], mode="lines",
                        name=sym, line=dict(color=palette[i % len(palette)], width=2.2),
                    ))
                ui_style.style_fig(fig, height=380)
                fig.update_yaxes(title="% change vs start", ticksuffix="%")
                st.plotly_chart(fig, use_container_width=True)

                # Correlation matrix on returns
                rets = pivot.pct_change().dropna()
                corr = rets.corr().round(2)
                st.markdown("**Daily-return correlation**")
                fig2 = go.Figure(data=go.Heatmap(
                    z=corr.values, x=corr.columns, y=corr.index,
                    colorscale=[[0, ui_style.BEAR], [0.5, "#1c2440"], [1, ui_style.BULL]],
                    zmid=0, zmin=-1, zmax=1,
                    text=corr.values, texttemplate="%{text:.2f}",
                    textfont=dict(size=13, color=ui_style.TEXT),
                ))
                ui_style.style_fig(fig2, height=320)
                fig2.update_layout(coloraxis_showscale=False)
                st.plotly_chart(fig2, use_container_width=True)
                st.caption("Higher correlation = these names tend to move together. "
                           "Useful when sizing — concentrating in highly correlated names ≈ a single bet.")

    # ===== POSITION SIZING =====
    elif tools_choice == "Position sizing":
        st.markdown("#### Position sizing calculator")
        st.caption("ATR-based stop loss → suggested share count for a defined risk. "
                   "Risk = (entry − stop) × shares. Set risk as % of account.")
        ps_col1, ps_col2 = st.columns([1, 1])
        with ps_col1:
            ps_sym = st.selectbox("Ticker", equity_syms, key="ps_sym")
            account_size = st.number_input("Account size ($)", min_value=100.0, value=10000.0, step=500.0)
            risk_pct = st.slider("Risk per trade (%)", 0.1, 5.0, 1.0, 0.1)
        with ps_col2:
            atr_mult = st.slider("ATR multiple for stop", 0.5, 5.0, 2.0, 0.5,
                                  help="Stop = entry − (ATR × multiple). Higher = wider stop, fewer shares.")
            override_entry = st.number_input("Entry override ($, 0 = use last close)",
                                              min_value=0.0, value=0.0, step=0.5)

        if ps_sym:
            from dk.indicators import ta as ta_mod
            snap = ta_mod.compute(ps_sym)
            entry = override_entry if override_entry > 0 else (snap.last_close or 0)
            atr = snap.atr14 or 0
            if entry > 0 and atr > 0:
                stop = entry - atr * atr_mult
                stop = max(0.01, stop)
                risk_dollars = account_size * (risk_pct / 100.0)
                risk_per_share = entry - stop
                shares = int(risk_dollars / risk_per_share) if risk_per_share > 0 else 0
                position_value = shares * entry
                position_pct = position_value / account_size * 100 if account_size else 0

                m1, m2, m3 = st.columns(3)
                m1.metric("Entry", f"${entry:,.2f}")
                m2.metric(f"Stop ({atr_mult}× ATR)", f"${stop:,.2f}",
                          f"-{(entry - stop) / entry * 100:.2f}%")
                m3.metric("ATR(14)", f"${atr:,.2f}")
                m4, m5, m6 = st.columns(3)
                m4.metric("Shares", f"{shares:,}")
                m5.metric("Position size", f"${position_value:,.2f}", f"{position_pct:.1f}% of account")
                m6.metric("Risk", f"${risk_dollars:,.2f}", f"{risk_pct:.2f}%")

                # R:R table for several profit targets
                st.markdown("**Reward scenarios**")
                rr_rows = []
                for rr in [1, 2, 3, 5]:
                    target = entry + risk_per_share * rr
                    profit = (target - entry) * shares
                    rr_rows.append({
                        "R:R": f"{rr}:1", "Target": f"${target:,.2f}",
                        "Move %": f"{(target - entry) / entry * 100:+.2f}%",
                        "P&L": f"${profit:,.2f}",
                    })
                st.table(pd.DataFrame(rr_rows))
            else:
                st.warning("Need both a current price and an ATR — refresh data first.")

    # ===== CUSTOM ALERTS =====
    elif tools_choice == "Custom alerts":
        st.markdown("#### Custom alerts")
        st.caption("Define your own price / RSI / sentiment triggers. Evaluated on every poll cycle. "
                   "Each rule fires at most once (then auto-disables — re-enable below).")

        ca_col1, ca_col2, ca_col3, ca_col4 = st.columns([1.0, 1.4, 1.0, 1.6])
        ca_sym = ca_col1.selectbox("Ticker", equity_syms, key="ca_sym")
        ca_kind = ca_col2.selectbox(
            "Trigger", [
                ("price_above", "Price above"),
                ("price_below", "Price below"),
                ("rsi_above", "RSI above"),
                ("rsi_below", "RSI below"),
                ("sentiment_above", "Sentiment 24h above"),
                ("sentiment_below", "Sentiment 24h below"),
            ],
            format_func=lambda x: x[1] if isinstance(x, tuple) else x,
            key="ca_kind",
        )
        ca_thr = ca_col3.number_input("Threshold", value=0.0, key="ca_thr")
        ca_note = ca_col4.text_input("Note (optional)", placeholder="e.g. add starter position",
                                      key="ca_note")
        if st.button("Add alert rule", type="primary", key="ca_add"):
            with sqlite3.connect(DB_PATH) as c:
                c.execute(
                    "INSERT INTO custom_alerts (symbol, kind, threshold, note) VALUES (?, ?, ?, ?)",
                    (ca_sym.upper(), ca_kind[0], float(ca_thr), ca_note or None),
                )
                c.commit()
            st.success(f"Added: {ca_sym} {ca_kind[1]} {ca_thr}")
            st.rerun()

        st.markdown("**Active rules**")
        rules = q("""SELECT id, symbol, kind, threshold, note, active, fired_at, created_at
                     FROM custom_alerts ORDER BY active DESC, created_at DESC""")
        if rules.empty:
            st.info("No custom alert rules yet.")
        else:
            for _, r in rules.iterrows():
                rc1, rc2, rc3, rc4, rc5 = st.columns([1.0, 2.5, 1.0, 1.0, 0.8])
                rc1.markdown(f"`{r['symbol']}`")
                rc2.markdown(f"{r['kind'].replace('_', ' ')} **{r['threshold']}**"
                              + (f" — *{r['note']}*" if r['note'] else ""))
                rc3.markdown("✓ active" if r["active"] else ("🔥 fired" if r["fired_at"] else "⏸ paused"))
                rc4.caption(str(r["created_at"])[:16])
                if rc5.button("Delete", key=f"ca_del_{r['id']}"):
                    with sqlite3.connect(DB_PATH) as c:
                        c.execute("DELETE FROM custom_alerts WHERE id=?", (int(r["id"]),))
                        c.commit()
                    st.rerun()

with tab_charts:
    st.subheader("TradingView charts")
    st.caption("Embedded TradingView widget. **If you sign in to TradingView in this same browser, "
               "your saved indicators and drawings will appear** — that's as close as TV's API allows. "
               "Below the chart: TV's proprietary technical rating across timeframes.")
    candidate_syms = [c["symbol"] for c in discovery.list_candidates()]
    chart_universe = sorted(set(equity_syms + candidate_syms))
    chart_sym = st.selectbox("Symbol", chart_universe, key="tv_chart_sym")

    # TradingView Advanced Chart — wrap in try/except so a TV outage can't break the page
    tv_exchange = "NASDAQ"
    try:
        import streamlit.components.v1 as components
        tv_html = f"""
        <div class="tradingview-widget-container" style="height:560px;">
          <div id="tradingview_widget"></div>
          <script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>
          <script type="text/javascript">
            new TradingView.widget({{
              "autosize": true,
              "symbol": "{tv_exchange}:{chart_sym}",
              "interval": "D",
              "timezone": "Etc/UTC",
              "theme": "dark",
              "style": "1",
              "locale": "en",
              "enable_publishing": false,
              "allow_symbol_change": true,
              "container_id": "tradingview_widget",
              "studies": ["MASimple@tv-basicstudies","RSI@tv-basicstudies","MACD@tv-basicstudies"],
              "withdateranges": true,
              "hide_side_toolbar": false,
              "details": true,
              "hotlist": true,
              "calendar": true
            }});
          </script>
        </div>
        """
        components.html(tv_html, height=580, scrolling=False)
    except Exception as e:
        st.warning(f"TradingView widget could not load: {e}. Use the chart studio in the Watchlist or Thesis tab as an alternative.")

    # TradingView ratings table for this symbol across intervals
    tv_df = q("""SELECT interval, recommendation, buy_signals, sell_signals,
                        neutral_signals, rsi, macd_hist, fetched_at
                 FROM tv_ratings WHERE symbol=? ORDER BY interval""",
              (chart_sym,))
    st.markdown("#### TradingView technical rating")
    if tv_df.empty:
        st.info("No TradingView ratings cached yet for this symbol. Click **Refresh data** "
                "in the toolbar to fetch the watchlist's ratings; for off-watchlist symbols "
                "use the Refresh button below.")
        if st.button(f"Fetch TV ratings for {chart_sym}"):
            with st.spinner(f":robot_face: Pulling TradingView technical ratings for {chart_sym} (3 timeframes)..."):
                from dk.sources import tradingview_ratings as tvr
                n = tvr.fetch_for_symbol(chart_sym, intervals=["1h", "1d", "1W"])
            st.success(f"Pulled {n} ratings for {chart_sym}")
            st.rerun()
    else:
        st.dataframe(tv_df, use_container_width=True, hide_index=True)
    st.caption(":bulb: Webhook alerts from TradingView land in the **Alerts** tab tagged "
               "`TRADINGVIEW`. See `dk/server/webhook.py` to set up.")

with tab_portfolio:
    st.subheader("Portfolio across brokers")
    st.caption(":lock: Read-only. Add credentials in `config/secrets.env` to connect a broker.")

    if st.button("Sync brokers now"):
        with st.spinner(":lock: Authenticating + pulling read-only positions from each configured broker..."):
            res = broker_sync.sync_all()
        st.json(res)
        st.rerun()

    status_df = q("SELECT broker, connected, last_sync, last_error, note FROM broker_status ORDER BY broker")
    configured = {b.name for b in configured_brokers()}
    all_known = ["coinbase", "robinhood", "blofin", "schwab"]
    rows = []
    for name in all_known:
        s = status_df[status_df["broker"] == name].iloc[0].to_dict() if not status_df.empty and name in status_df["broker"].values else {}
        rows.append({
            "broker": name,
            "configured": "✓" if name in configured else "—",
            "connected": "✓" if s.get("connected") else "—",
            "last_sync": s.get("last_sync") or "—",
            "note": s.get("note") or s.get("last_error") or "",
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    # Positions table
    pos = q("""SELECT broker, symbol, asset_type, quantity, avg_cost, market_price,
                      market_value, unrealized_pnl, fetched_at
               FROM positions WHERE quantity > 0 ORDER BY market_value DESC NULLS LAST""")
    if pos.empty:
        st.info("No positions synced yet. Configure at least one broker in `config/secrets.env`, "
                "then click **Sync brokers now**.")
    else:
        total_mv = pos["market_value"].sum(skipna=True)
        total_pnl = pos["unrealized_pnl"].sum(skipna=True)
        c1, c2, c3 = st.columns(3)
        c1.metric("Total market value", f"${total_mv:,.2f}" if total_mv else "—")
        c2.metric("Unrealized P&L", f"${total_pnl:+,.2f}" if total_pnl else "—")
        c3.metric("Holdings", f"{len(pos)}")
        st.dataframe(
            pos.round({"quantity": 4, "avg_cost": 2, "market_price": 2,
                       "market_value": 2, "unrealized_pnl": 2}),
            use_container_width=True, hide_index=True,
            column_config={
                "market_value": st.column_config.NumberColumn("market value", format="$%.2f"),
                "unrealized_pnl": st.column_config.NumberColumn("unreal P&L", format="$%+.2f"),
                "market_price": st.column_config.NumberColumn("price", format="$%.2f"),
                "avg_cost": st.column_config.NumberColumn("avg cost", format="$%.2f"),
            },
        )

    with st.expander("How to connect a broker"):
        for cls in _ALL_BROKER_CLASSES:
            try:
                inst = cls()
                st.markdown(f"**{inst.name}** — {inst.setup_hint()}")
            except Exception as e:
                st.markdown(f"_(broker init error: {e})_")

with tab_thesis:
    st.subheader("Deep-dive thesis")
    st.caption("Pick any ticker (watchlist or discovered candidate) to see the full breakdown.")
    candidate_syms = [c["symbol"] for c in discovery.list_candidates()]
    universe = sorted(set(equity_syms + candidate_syms))
    th_sym = st.selectbox("Ticker", universe, key="thesis_sym")
    if st.button("Build thesis", type="primary"):
        with st.spinner(f":mag: Building thesis for {th_sym} — pulling business meta, indicators, sentiment, catalysts..."):
            t = thesis_gen.build(th_sym)
        if th_sym.upper() in OWNED:
            st.success(f":lock: You hold {th_sym} in a connected broker account.")
        st.markdown(t.narrative)
        st.markdown("---")
        st.markdown("#### Chart studio")
        chart_studio.render(th_sym, key=f"thesis_studio_{th_sym}", default_period="6mo")

    # ---- Notes / journal ----
    st.markdown("---")
    st.markdown(f"#### :memo: Notes & journal — `{th_sym}`")
    with st.expander("Add a note", expanded=False):
        note_body = st.text_area("What do you want to remember?",
                                  placeholder="e.g. Watching for $80 close as confirmation. "
                                              "If earnings beat + positive guide → add starter position.",
                                  key=f"note_body_{th_sym}", height=100)
        nc1, nc2, nc3 = st.columns([2, 1, 1])
        note_tags = nc1.text_input("Tags (comma-separated)",
                                    placeholder="setup, watching, position",
                                    key=f"note_tags_{th_sym}")
        note_pin = nc2.checkbox("Pin", key=f"note_pin_{th_sym}")
        if nc3.button("Save note", type="primary", key=f"note_save_{th_sym}"):
            if note_body.strip():
                notes_mod.add(th_sym, note_body, note_tags, pinned=note_pin)
                st.toast("Note saved", icon="✓")
                st.rerun()
            else:
                st.warning("Empty note — write something first.")

    notes = notes_mod.list_for(th_sym)
    if not notes:
        st.caption("No notes yet for this ticker.")
    else:
        for n in notes:
            pinmark = ":pushpin: " if n["pinned"] else ""
            tags = f"<span style='color:#8b95ad;font-size:11px;'>{n['tags']}</span>" if n["tags"] else ""
            st.markdown(
                f"<div style='background:#151b2c;border:1px solid #2a3550;border-radius:10px;"
                f"padding:10px 14px;margin:8px 0;'>"
                f"<div style='color:#8b95ad;font-size:11px;margin-bottom:4px;'>"
                f"{pinmark}{n['created_at']} {tags}</div>"
                f"<div>{n['body']}</div></div>",
                unsafe_allow_html=True,
            )
            cdel1, cdel2, _ = st.columns([1, 1, 4])
            if cdel1.button("Pin/unpin", key=f"npin_{n['id']}"):
                notes_mod.update(n["id"], pinned=not n["pinned"])
                st.rerun()
            if cdel2.button("Delete", key=f"ndel_{n['id']}"):
                notes_mod.delete(n["id"])
                st.rerun()

with tab_discover:
    st.subheader("Multi-source trending")
    st.caption("Combines Reddit (r/wallstreetbets, r/stocks), StockTwits trending, and DK's "
               "own news-mention scanner. Tickers showing up across multiple sources are "
               "where retail attention is concentrating.")
    trending_df = q("""
        SELECT symbol,
               SUM(CASE WHEN source='reddit_wsb' THEN mention_count ELSE 0 END) AS reddit_wsb,
               SUM(CASE WHEN source='reddit_stocks' THEN mention_count ELSE 0 END) AS reddit_stocks,
               SUM(CASE WHEN source='stocktwits' THEN mention_count ELSE 0 END) AS stocktwits,
               AVG(CASE WHEN source='stocktwits' THEN sentiment END) AS twit_sent,
               COUNT(DISTINCT source) AS sources
        FROM trending_mentions
        GROUP BY symbol
        ORDER BY (SUM(mention_count) + COUNT(DISTINCT source) * 5) DESC
        LIMIT 25
    """)
    if trending_df.empty:
        st.info("No trending data yet — click **Refresh data** in the toolbar.")
    else:
        watchlist_set = set(equity_syms)
        trending_df["on_watchlist"] = trending_df["symbol"].apply(
            lambda s: "✓" if s in watchlist_set else "")
        clickable_table(
            trending_df.round({"twit_sent": 2}),
            key="trending_table",
            column_config={
                "twit_sent": st.column_config.NumberColumn("twits sentiment", format="%+.2f"),
                "sources": st.column_config.NumberColumn("# sources", format="%d"),
            },
        )
        st.caption(":bulb: Click any row for the chart preview. Tickers appearing on **multiple sources** "
                   "are stronger signals than single-source noise.")
    st.markdown("---")

    st.subheader("Discovered candidates")
    st.caption("Symbols mined from recent news that aren't already on your watchlist. "
               "Validated through yfinance (real ticker, market cap > $200M, price > $1).")
    col_a, col_b = st.columns([1, 1])
    if col_a.button("Run discovery scan now"):
        with st.spinner(":telescope: Mining news headlines for tickers, validating each via yfinance, scoring through opportunity engine..."):
            res = discovery.scan(min_mentions=3, max_validate=20)
        st.success(f"Validated {res['validated']} candidates "
                   f"({res['rejected']} rejected, {res['raw_count']} raw mentions).")
        st.json(res)
    cands = discovery.list_candidates()
    if not cands:
        st.info("No discovered candidates yet. Run a scan above (or refresh data — discovery runs in the poll cycle).")
    else:
        df = pd.DataFrame(cands)
        df["mcap_M"] = (df["market_cap"] / 1e6).round(0)
        view = df[["symbol", "name", "sector", "score", "score_direction",
                   "mention_count", "last_price", "mcap_M",
                   "discovered_via", "first_seen", "last_seen"]]
        clickable_table(
            view, key="discover_table",
            column_config={
                "score": st.column_config.ProgressColumn(
                    "score", min_value=0, max_value=100, format="%.1f"),
                "mcap_M": st.column_config.NumberColumn("mkt cap ($M)", format="%.0f"),
                "last_price": st.column_config.NumberColumn("price", format="$%.2f"),
                "mention_count": st.column_config.NumberColumn("mentions", format="%d"),
            },
        )
        st.caption(":bulb: Click any row to pop a chart preview, or switch to the **Thesis** tab "
                   "for the full deep-dive.")

with tab_opps:
    # Daily digest panel
    with st.expander(":newspaper: Daily digest — what changed today", expanded=True):
        st.markdown(digest_mod.build())

    st.subheader("Opportunity ranking")
    st.caption(":bulb: Composite signal — magnitude shows attention-worthiness, "
               "direction shows bull/bear lean. Not a buy/sell call.")

    # Daily discoveries banner
    discoveries = opp_delta.daily_discoveries(limit=5)
    if discoveries:
        st.markdown("##### :rocket: Today's discoveries (rank movers, last 24h)")
        cols = st.columns(min(len(discoveries), 5))
        for col, d in zip(cols, discoveries):
            arrow = "▲" if (d.get("rank_chg") or 0) > 0 else ("▼" if (d.get("rank_chg") or 0) < 0 else "·")
            color = "green" if arrow == "▲" else ("red" if arrow == "▼" else "gray")
            col.markdown(
                f"**:{color}[{arrow}{abs(d.get('rank_chg') or 0)}]** `{d['symbol']}`  \n"
                f"<small>#{d['rank_then']}→#{d['rank_now']} · score "
                f"{d['score_then']:.1f}→{d['score_now']:.1f} ({d['score_chg']:+.1f})</small>",
                unsafe_allow_html=True,
            )
        st.markdown("---")

    ranked = opp_delta.get_with_deltas()
    if not ranked:
        st.info("Need price + news data first — refresh from the sidebar.")
    else:
        df = pd.DataFrame(ranked)

        def _arrow(x):
            if x is None:
                return "—"
            if x > 0:
                return f"▲{int(x)}"
            if x < 0:
                return f"▼{int(abs(x))}"
            return "·"
        df["Δrank"] = df["rank_chg"].apply(_arrow)

        df["owned"] = df["symbol"].apply(lambda s: "✓" if s.upper() in OWNED else "")
        # Pull TradingView rating for each symbol (1d) for a TV column
        tv_rec = q("SELECT symbol, recommendation FROM tv_ratings WHERE interval='1d'")
        tv_map = dict(zip(tv_rec["symbol"], tv_rec["recommendation"])) if not tv_rec.empty else {}
        df["TV"] = df["symbol"].map(tv_map).fillna("—")
        view = df[[
            "rank", "Δrank", "symbol", "owned", "TV", "score", "score_chg", "direction",
            "price_mom", "vol_mom", "news_vel", "sentiment", "earn_prox",
            "headline_count_24h", "next_earnings",
        ]]
        clickable_table(
            view, key="opps_table",
            column_config={
                "rank": st.column_config.NumberColumn("#", format="%d"),
                "score": st.column_config.ProgressColumn(
                    "score", min_value=0, max_value=100, format="%.1f"),
                "score_chg": st.column_config.NumberColumn("Δscore", format="%+.1f"),
                "price_mom": st.column_config.NumberColumn("price mom", format="%+.2f"),
                "vol_mom": st.column_config.NumberColumn("vol mom", format="%+.2f"),
                "news_vel": st.column_config.NumberColumn("news vel", format="%+.2f"),
                "sentiment": st.column_config.NumberColumn("sentiment", format="%+.2f"),
                "earn_prox": st.column_config.NumberColumn("earn prox", format="%.2f"),
                "headline_count_24h": st.column_config.NumberColumn("24h news", format="%d"),
            },
        )
        st.caption(":bulb: Click any row to pop a chart preview. "
                   "Components clipped to [-1, 1] then weighted: price 25 / vol 15 / news 15 / sentiment 30 / earn 15. "
                   "Δrank/Δscore are vs the previous snapshot.")

        # Score-over-time chart for focus ticker
        st.markdown("---")
        st.markdown("#### Score history")
        chart_sym = st.selectbox(
            "Trace a ticker's opportunity score over time",
            df["symbol"].tolist(),
            key="score_chart_sym",
        )
        hist = q("""SELECT snapshot_ts, score, rank, sentiment, price_mom
                    FROM score_history WHERE symbol=? ORDER BY snapshot_ts ASC""",
                 (chart_sym,))
        if hist.empty or len(hist) < 2:
            st.caption(f"Not enough history yet for {chart_sym}. Snapshots accrue with each poll — "
                       "let the scheduler run for a few cycles.")
        else:
            import plotly.graph_objects as go
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=hist["snapshot_ts"], y=hist["score"],
                                      mode="lines+markers", name="opportunity score",
                                      line=ui_style.LINE_PRIMARY,
                                      fill="tozeroy",
                                      fillcolor="rgba(0,212,170,0.10)"))
            ui_style.style_fig(fig, height=320)
            fig.update_yaxes(title="score (0-100)", range=[0, 100])
            st.plotly_chart(fig, use_container_width=True)

with tab_alerts:
    st.subheader("Active alerts")
    df = q("""SELECT id, created_at, symbol, kind, message, seen
              FROM alerts ORDER BY created_at DESC LIMIT 200""")
    if df.empty:
        st.info("No alerts yet — refresh data to evaluate.")
    else:
        unseen_df = df[df["seen"] == 0]
        seen_df = df[df["seen"] == 1]
        if not unseen_df.empty:
            st.markdown("#### :rotating_light: Unseen")
            for _, row in unseen_df.iterrows():
                st.warning(f"**{row['kind']}** · {row['symbol']} — {row['message']}  \n*{row['created_at']}*")
        if not seen_df.empty:
            with st.expander(f"Seen ({len(seen_df)})"):
                st.dataframe(seen_df[["created_at", "symbol", "kind", "message"]],
                             use_container_width=True, hide_index=True)

with tab_watch:
    st.subheader("Watchlist")

    # ---- Add ticker form ----
    with st.expander("➕  Add a ticker to your watchlist", expanded=False):
        st.caption("Validated against yfinance. Backfills 3 months of price history immediately. "
                   "Added entries land in `config/watchlist_user.yaml`.")
        c1, c2, c3, c4 = st.columns([1.2, 2.0, 1.0, 1.0])
        new_sym = c1.text_input("Ticker", placeholder="e.g. PLTR", key="add_sym").strip().upper()
        new_name = c2.text_input("Name (optional)", placeholder="auto-fetched if blank", key="add_name").strip()
        new_kind = c3.selectbox("Type", ["equities", "etfs", "crypto"], key="add_kind")
        new_region = c4.selectbox("Region", ["US", "EU", "ASIA", "GLOBAL"], key="add_region")

        gecko_id = None
        if new_kind == "crypto":
            gecko_id = st.text_input("CoinGecko ID (e.g. solana, cardano)",
                                      placeholder="lowercase coingecko id", key="add_gecko").strip()

        add_clicked = st.button("Add to watchlist", type="primary", key="add_btn")
        if add_clicked:
            if not new_sym:
                st.error("Ticker is required.")
            elif new_kind in ("equities", "etfs"):
                # Validate via yfinance
                with st.spinner(f":mag: Validating {new_sym} via yfinance and backfilling 3 months of price history..."):
                    try:
                        import yfinance as yf
                        t = yf.Ticker(new_sym)
                        info = t.fast_info
                        price = float(getattr(info, "last_price", 0) or 0)
                    except Exception as e:
                        price = 0
                        st.error(f"yfinance lookup failed: {e}")
                if price <= 0:
                    st.error(f"Could not validate {new_sym} — symbol may not exist on Yahoo. "
                             "Check the ticker and try again.")
                else:
                    name_to_save = new_name
                    if not name_to_save:
                        try:
                            full = (t.info or {})
                            name_to_save = full.get("shortName") or full.get("longName") or new_sym
                        except Exception:
                            name_to_save = new_sym
                    added = add_to_watchlist(new_sym, name_to_save, kind=new_kind, region=new_region)
                    if not added:
                        st.warning(f"{new_sym} is already on the watchlist.")
                    else:
                        # Backfill prices immediately so the rest of the system has data
                        from dk.sources import prices_yfinance
                        n = prices_yfinance.fetch_prices(new_sym)
                        st.success(f"Added {new_sym} ({name_to_save}) — {n} price bars backfilled.")
                        st.rerun()
            else:  # crypto
                if not gecko_id:
                    st.error("CoinGecko ID is required for crypto entries (e.g. 'solana', 'cardano').")
                else:
                    added = add_to_watchlist(new_sym, new_name or new_sym, kind="crypto",
                                             coingecko_id=gecko_id)
                    if not added:
                        st.warning(f"{new_sym} is already on the watchlist.")
                    else:
                        st.success(f"Added crypto {new_sym} (CoinGecko: {gecko_id}). "
                                   "Prices populate on next refresh.")
                        st.rerun()

    # ---- Remove user-added tickers ----
    user_data = _load_user_additions_fn()
    user_syms = []
    for kind in ("equities", "etfs", "crypto"):
        for e in user_data.get(kind, []):
            user_syms.append((e.get("symbol", "?"), kind))
    if user_syms:
        with st.expander(f"⊖  Remove user-added tickers ({len(user_syms)})", expanded=False):
            for sym, kind in user_syms:
                rc1, rc2, rc3 = st.columns([1, 2, 1])
                rc1.markdown(f"`{sym}`")
                rc2.caption(f"type: {kind}")
                if rc3.button("Remove", key=f"rm_{sym}"):
                    remove_from_watchlist(sym)
                    st.success(f"Removed {sym}")
                    st.rerun()

    st.markdown("---")
    st.markdown("#### Latest close")
    rows = q("""
        SELECT p.symbol, p.ts, p.close, p.volume,
          (SELECT close FROM prices p2
           WHERE p2.symbol=p.symbol AND p2.ts < p.ts
           ORDER BY p2.ts DESC LIMIT 1) AS prior_close
        FROM prices p
        INNER JOIN (SELECT symbol, MAX(ts) m FROM prices GROUP BY symbol) lat
          ON p.symbol=lat.symbol AND p.ts=lat.m
        ORDER BY p.symbol
    """)
    if rows.empty:
        st.info("No price data yet. Click **Refresh data now** in the toolbar.")
    else:
        rows["chg_pct"] = (rows["close"] - rows["prior_close"]) / rows["prior_close"] * 100
        clickable_table(
            rows[["symbol", "close", "chg_pct", "volume", "ts"]].round({"close": 2, "chg_pct": 2}),
            key="watchlist_table",
            column_config={"chg_pct": st.column_config.NumberColumn("chg %", format="%+.2f%%")},
        )
        st.caption(":bulb: Click any row to pop a chart preview.")

    if focus != "(all)":
        st.markdown(f"### {focus} — chart studio")
        chart_studio.render(focus, key=f"watch_studio_{focus}", default_period="3mo")

with tab_sentiment:
    st.subheader("Per-ticker sentiment (last 24h)")
    df = q("""SELECT symbol, AVG(sentiment) AS avg_sentiment, COUNT(*) AS articles
              FROM news
              WHERE symbol IS NOT NULL AND sentiment IS NOT NULL
                AND fetched_at >= datetime('now', '-1 day')
              GROUP BY symbol ORDER BY ABS(AVG(sentiment)) DESC""")
    if df.empty:
        st.info("No scored news yet — refresh from the sidebar.")
    else:
        df["tone"] = df["avg_sentiment"].apply(senti_label)
        clickable_table(
            df.round({"avg_sentiment": 3}),
            key="sentiment_table",
            column_config={
                "avg_sentiment": st.column_config.NumberColumn("avg sentiment", format="%+.3f"),
            },
        )
        st.caption(":bulb: Click any row to pop a chart preview.")

with tab_news:
    st.subheader("News feed")
    placeholders = ",".join("?" * len(selected_regions)) if selected_regions else "''"
    if focus != "(all)":
        df = q(f"""SELECT published, source, region, title, url, symbol, sentiment
                   FROM news WHERE symbol = ?
                   ORDER BY published DESC LIMIT 200""", (focus,))
    else:
        df = q(f"""SELECT published, source, region, title, url, symbol, sentiment
                   FROM news WHERE region IN ({placeholders}) OR symbol IS NOT NULL
                   ORDER BY published DESC LIMIT 200""", tuple(selected_regions))
    if df.empty:
        st.info("No news yet — refresh from the sidebar.")
    else:
        for _, row in df.iterrows():
            tag = f"`{row['symbol']}`" if row['symbol'] else f"_{row['region'] or 'GLOBAL'}_"
            tone = senti_label(row["sentiment"])
            color = "green" if tone == "+" else ("red" if tone == "-" else "gray")
            st.markdown(
                f"- :{color}[**{tone}**] {tag} **[{row['title']}]({row['url']})**  \n"
                f"  <small>{row['source']} · {row['published']} · score {row['sentiment']:.2f}</small>"
                if row["sentiment"] is not None else
                f"- {tag} **[{row['title']}]({row['url']})**  \n"
                f"  <small>{row['source']} · {row['published']}</small>",
                unsafe_allow_html=True,
            )

with tab_earnings:
    st.subheader("Upcoming earnings")
    df = q("""SELECT symbol, report_date, eps_estimate, revenue_estimate
              FROM earnings WHERE report_date >= date('now')
              ORDER BY report_date ASC LIMIT 100""")
    if df.empty:
        st.info("No earnings rows yet.")
    else:
        st.dataframe(df, use_container_width=True, hide_index=True)

with tab_calendar:
    st.subheader("Macro events")
    macro = q("""SELECT event_date, category, title, importance, region
                 FROM macro_events
                 WHERE event_date >= date('now')
                 ORDER BY event_date ASC LIMIT 60""")
    if macro.empty:
        st.info("No macro events loaded yet — refresh.")
    else:
        st.dataframe(
            macro, use_container_width=True, hide_index=True,
            column_config={"importance": st.column_config.ProgressColumn(
                "imp", min_value=0, max_value=3, format="%d")},
        )
    st.markdown("---")
    st.subheader("Upcoming IPOs")
    ipos = q("""SELECT expected_date, symbol, name, price_range, exchange, source
                FROM ipos
                WHERE expected_date >= date('now', '-30 days')
                ORDER BY expected_date DESC LIMIT 100""")
    if ipos.empty:
        st.info("No IPO data yet. Add a `FINNHUB_KEY` in `config/secrets.env` "
                "for the Finnhub IPO calendar; SEC S-1 filings come in via RSS regardless.")
    else:
        st.dataframe(ipos, use_container_width=True, hide_index=True)

with tab_crypto:
    st.subheader("Crypto snapshot")
    df = q("""SELECT cp.symbol, cp.ts, cp.price_usd, cp.change_24h_pct, cp.vol_24h, cp.market_cap
              FROM crypto_prices cp
              INNER JOIN (SELECT symbol, MAX(ts) m FROM crypto_prices GROUP BY symbol) lat
                ON cp.symbol=lat.symbol AND cp.ts=lat.m
              ORDER BY cp.symbol""")
    if df.empty:
        st.info("No crypto data yet.")
    else:
        clickable_table(
            df.round({"price_usd": 2, "change_24h_pct": 2}),
            key="crypto_table",
            column_config={"change_24h_pct": st.column_config.NumberColumn("24h chg", format="%+.2f%%")},
        )
        st.caption(":bulb: Click any row to pop a chart preview.")
