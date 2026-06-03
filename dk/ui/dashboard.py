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

if "_dk_theme" not in st.session_state:
    st.session_state["_dk_theme"] = "dark"
ui_style.inject(st.session_state["_dk_theme"])
store.init_db()


# ---- In-process background scheduler (Railway / always-on hosts) ----
# When DK_INPROCESS_SCHEDULER=1, run the 15-min poller inside this process so a
# single Railway service powers both the dashboard AND auto-updates. Gated by
# env var so local dev (separate scheduler window) and Streamlit Cloud don't
# double-poll. @st.cache_resource guarantees it starts exactly once per process.
import os as _os
if _os.getenv("DK_INPROCESS_SCHEDULER") == "1":
    @st.cache_resource
    def _bg_scheduler():
        from dk.jobs.scheduler import start_background_scheduler
        return start_background_scheduler(run_now=True)
    _bg_scheduler()


def q(sql: str, params: tuple = ()) -> pd.DataFrame:
    with sqlite3.connect(DB_PATH, timeout=10) as c:
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
tb_col1, tb_col2, tb_col3, tb_col4, tb_col5 = st.columns([1.4, 1.2, 1.9, 1.3, 1.1])

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
    _cur_theme = st.session_state.get("_dk_theme", "dark")
    _theme_choice = st.radio(
        "Theme", ["🌙 Dark", "☀️ Light"],
        index=0 if _cur_theme == "dark" else 1,
        horizontal=True, label_visibility="collapsed", key="_dk_theme_widget",
    )
    _new_theme = "light" if "Light" in _theme_choice else "dark"
    if _new_theme != _cur_theme:
        st.session_state["_dk_theme"] = _new_theme
        st.rerun()

st.markdown('</div>', unsafe_allow_html=True)

# Handle toolbar actions — SIMPLE + STABLE (no auto-rerun loops that can blank the page)
_just_triggered = False
if refresh_clicked:
    import os as _os_rf
    if _os_rf.getenv("DK_INPROCESS_SCHEDULER") == "1":
        # Hosted: trigger the background scheduler to poll now. Non-blocking,
        # and crucially NO st.rerun() — the banner below renders on this same
        # pass. Nothing here can freeze or blank the page.
        try:
            from dk.jobs.scheduler import trigger_now
            if trigger_now():
                _just_triggered = True
                st.toast("🔄 Refresh started — new data in ~30–45s.", icon="🔄")
            else:
                st.toast("Scheduler warming up — wait a few seconds and try again.", icon="⏳")
        except Exception as e:
            st.toast(f"Couldn't start refresh: {e}", icon="⚠️")
    else:
        # Local / no background scheduler: blocking poll with a spinner.
        with st.spinner("🔄 Refreshing DK data (~30–45s)..."):
            try:
                summary = poller.run_once()
                st.session_state["_dk_last_summary"] = summary
            except Exception as e:
                import traceback
                st.error(f"Refresh failed: **{type(e).__name__}** — {e}")
                st.code(traceback.format_exc(), language="python")
                st.stop()
        st.toast("Refresh complete!", icon="✅")

# ---- Static loading banner (renders once; no fragment, no auto-rerun) ----
_poll_running = _just_triggered
try:
    _ps = store.get_poll_status()
    if _ps.get("status") == "running":
        _poll_running = True
        # staleness guard — don't show forever if a poll crashed
        if _ps.get("started_at"):
            from datetime import datetime, timezone
            try:
                _stt = datetime.fromisoformat(_ps["started_at"].replace("Z", "+00:00"))
                if _stt.tzinfo is None:
                    _stt = _stt.replace(tzinfo=timezone.utc)
                if (datetime.now(timezone.utc) - _stt).total_seconds() > 240:
                    _poll_running = _just_triggered  # ignore stale 'running'
            except Exception:
                pass
except Exception:
    pass

if _poll_running:
    st.markdown(ui_style.loading_banner(), unsafe_allow_html=True)
    if st.button("↻ Reload to show new data", key="reload_check", type="primary"):
        st.rerun()

# Show the last run summary (after a local refresh completes)
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

(tab_now, tab_markets, tab_opps, tab_thesis, tab_themes, tab_charts, tab_discover,
 tab_tools, tab_alerts, tab_watch, tab_portfolio, tab_sentiment, tab_news,
 tab_earnings, tab_calendar, tab_crypto) = st.tabs(
    ["📡 Now", "🏆 Markets", "Opportunities", "Thesis", "Themes", "Charts", "Discover",
     "Tools", f"Alerts ({unseen})", "Watchlist", "Portfolio", "Sentiment", "News",
     "Earnings", "Calendar", "Crypto"]
)

with tab_markets:
    from dk.sources import leaderboards as _lb

    @st.cache_data(ttl=900, show_spinner=False)
    def _lb_crypto():
        return _lb.top_crypto(25)

    @st.cache_data(ttl=900, show_spinner=False)
    def _lb_stocks():
        return _lb.top_stocks(25)

    @st.cache_data(ttl=900, show_spinner=False)
    def _lb_etfs():
        return _lb.top_etfs()

    @st.cache_data(ttl=900, show_spinner=False)
    def _lb_dividend():
        return _lb.top_dividend()

    st.subheader("🏆 Markets — top 25 leaderboards")
    st.caption("One-stop board: the biggest/most-active names across stocks, ETFs, dividend payers "
               "and crypto. Live data, cached ~15 min. Click into Thesis/Charts for any name.")

    board = st.radio("Board", ["📈 Stocks", "📊 ETFs", "💰 Dividend", "🪙 Crypto"],
                     horizontal=True, label_visibility="collapsed", key="lb_board")

    if st.button("↻ Refresh leaderboards", key="lb_refresh"):
        st.cache_data.clear()
        st.rerun()

    def _pct_col(label="chg %"):
        return st.column_config.NumberColumn(label, format="%+.2f%%")

    if board == "📈 Stocks":
        st.markdown("#### Top 25 most-active stocks")
        rows = _lb_stocks()
        if not rows:
            st.info("Couldn't load stocks right now — try Refresh.")
        else:
            df = pd.DataFrame(rows)
            df["mcap_B"] = (df["market_cap"] / 1e9).round(1)
            view = df[["symbol", "name", "price", "change_pct", "mcap_B", "pe", "volume"]]
            clickable_table(view, key="lb_stocks_tbl", column_config={
                "price": st.column_config.NumberColumn("price", format="$%.2f"),
                "change_pct": _pct_col(), "mcap_B": st.column_config.NumberColumn("mkt cap ($B)", format="%.1f"),
                "pe": st.column_config.NumberColumn("P/E", format="%.1f"),
            })
            st.caption(":bulb: Click any row for a chart preview.")

    elif board == "📊 ETFs":
        st.markdown("#### Top 25 ETFs by assets")
        rows = _lb_etfs()
        df = pd.DataFrame(rows)
        view = df[["symbol", "name", "price", "change_pct"]]
        clickable_table(view, key="lb_etf_tbl", column_config={
            "price": st.column_config.NumberColumn("price", format="$%.2f"),
            "change_pct": _pct_col(),
        })
        st.caption(":bulb: Click any row for a chart preview.")

    elif board == "💰 Dividend":
        st.markdown("#### Top 25 dividend stocks (by yield)")
        rows = _lb_dividend()
        df = pd.DataFrame(rows)
        view = df[["symbol", "name", "price", "change_pct", "yield_pct", "div"]]
        clickable_table(view, key="lb_div_tbl", column_config={
            "price": st.column_config.NumberColumn("price", format="$%.2f"),
            "change_pct": _pct_col(),
            "yield_pct": st.column_config.NumberColumn("yield", format="%.2f%%"),
            "div": st.column_config.NumberColumn("annual div", format="$%.2f"),
        })
        st.caption("Yield computed live from price and annual dividend. Click any row for a chart preview.")

    else:  # Crypto
        st.markdown("#### Top 25 crypto by market cap")
        rows = _lb_crypto()
        df = pd.DataFrame(rows)
        df["mcap_B"] = (df["market_cap"] / 1e9).round(2)
        view = df[["rank", "symbol", "name", "price", "change_24h", "change_7d", "mcap_B"]]
        st.dataframe(view, use_container_width=True, hide_index=True, column_config={
            "rank": st.column_config.NumberColumn("#", format="%d"),
            "price": st.column_config.NumberColumn("price", format="$%.4f"),
            "change_24h": _pct_col("24h"), "change_7d": _pct_col("7d"),
            "mcap_B": st.column_config.NumberColumn("mkt cap ($B)", format="%.2f"),
        })

with tab_now:
    from dk.briefing import radar as radar_mod
    from dk.briefing import health as health_mod

    # ---- System status (diagnostic) ----
    _h = health_mod.gather()
    _label, _diag = health_mod.verdict(_h)
    with st.expander(f"🩺 System status — {_label}", expanded=("🟢" not in _label)):
        st.markdown(f"**{_label}** — {_diag}")
        rc = _h.get("row_counts", {})
        d1, d2, d3, d4 = st.columns(4)
        d1.metric("Price rows", rc.get("prices", "—"))
        d2.metric("News rows", rc.get("news", "—"))
        d3.metric("Score snapshots", rc.get("score_history", "—"))
        d4.metric("Alerts", rc.get("alerts", "—"))
        d5, d6, d7, d8 = st.columns(4)
        d5.metric("Scheduler", "running" if _h.get("scheduler_running") else "stopped")
        d6.metric("Poll status", _h.get("poll_status", "—"))
        d7.metric("DB writable", "yes" if _h.get("db_writable") else "NO")
        d8.metric("Mkt sentiment", rc.get("market_sentiment", "—"))
        st.caption(f"DB: `{_h.get('db_path')}` · last poll finished: {_h.get('poll_finished_at') or '—'}")
        if _h.get("last_summary"):
            st.markdown("**Last poll counts:**")
            st.json(_h["last_summary"])
        st.caption("Env: " + ", ".join(f"{k}={v}" for k, v in (_h.get('env') or {}).items()))

    st.subheader("📡 What matters now")
    st.caption("Your live briefing — synthesized from news, price action, sentiment, power players, "
               "and catalysts. Pointing out what's worth your attention, not telling you what to trade.")

    # ---- Opportunity Spotlight: where positive signals are converging ----
    spotlight = radar_mod.opportunity_spotlight(limit=5)
    st.markdown("### ⭐ Opportunities lining up")
    if not spotlight:
        st.info("No strong setups detected yet. Click **Refresh data** to pull the latest, "
                "then check back — this fills in as signals converge.")
    else:
        st.caption("Names where multiple positive signals are stacking up right now. "
                   "The more reasons listed, the more is going for it.")
        for s in spotlight:
            owned_tag = " :green-background[OWNED]" if s["owned"] else ""
            reasons_str = " · ".join(s["reasons"])
            catalyst = ""
            if s.get("catalyst_headline"):
                cat_url = s.get("catalyst_url") or "#"
                catalyst = (f"<div style='margin-top:6px;color:#8b95ad;font-size:12px;'>"
                            f"📰 Why now: <a href='{cat_url}' target='_blank' "
                            f"style='color:#4ea1ff;text-decoration:none;'>"
                            f"{s['catalyst_headline'][:120]}</a></div>")
            conv = s["conviction"]
            bar_w = min(100, conv)
            st.markdown(
                f"<div style='background:{ui_style.CARD};border:1px solid {ui_style.BORDER};"
                f"border-left:4px solid {ui_style.BULL};border-radius:10px;padding:14px 16px;margin:8px 0;'>"
                f"<div style='display:flex;justify-content:space-between;align-items:center;'>"
                f"<div style='font-size:18px;font-weight:800;color:{ui_style.TEXT};'>"
                f"{s['symbol']}{owned_tag} "
                f"<span style='font-size:12px;color:{ui_style.BULL};font-weight:600;'>"
                f"#{s['rank']} · score {s['score']:.0f} · {s['direction']}</span></div>"
                f"<div style='color:{ui_style.BULL};font-weight:700;font-size:13px;'>"
                f"conviction {conv:.0f}</div></div>"
                f"<div style='margin-top:6px;color:{ui_style.TEXT};font-size:13px;'>"
                f"✅ {reasons_str}</div>"
                f"{catalyst}"
                f"</div>",
                unsafe_allow_html=True,
            )
        st.caption(":bulb: Open the **Thesis** tab on any of these for the full deep-dive, "
                   "or click its row in **Opportunities** for a chart preview.")

    # ---- Market-wide scan (the WHOLE market, not just the watchlist) ----
    from dk.discovery import market_scan as _mscan
    st.markdown("### 🌍 Market scan — opportunities beyond your watchlist")
    st.caption("Biggest movers across the entire market right now, heat-scored with volume, "
               "news tone and Reddit buzz. These are NOT on your watchlist unless tagged.")
    market_ops = _mscan.top_market_opportunities(limit=12, exclude_watchlist=True)
    if not market_ops:
        st.info("No market scan data yet — click **Refresh data**, then **↻ Reload** after ~45s. "
                "The scan pulls the day's gainers/losers/most-active across all US stocks.")
    else:
        mcols = st.columns(2)
        for i, o in enumerate(market_ops):
            direction = o.get("score_direction", "flat")
            border = (ui_style.BULL if direction == "bull"
                      else ui_style.BEAR if direction == "bear" else ui_style.NEUTRAL)
            dir_icon = "▲" if direction == "bull" else ("▼" if direction == "bear" else "•")
            mc = o.get("market_cap")
            mc_str = (f"${mc/1e9:.1f}B" if mc and mc >= 1e9
                      else (f"${mc/1e6:.0f}M" if mc else "—"))
            price = o.get("last_price")
            price_str = f"${price:,.2f}" if price else "—"
            mcols[i % 2].markdown(
                f"<div style='background:{ui_style.CARD};border:1px solid {ui_style.BORDER};"
                f"border-left:4px solid {border};border-radius:10px;padding:11px 14px;margin:6px 0;'>"
                f"<div style='display:flex;justify-content:space-between;'>"
                f"<span style='font-size:16px;font-weight:800;color:{ui_style.TEXT};'>"
                f"{dir_icon} {o['symbol']}</span>"
                f"<span style='color:{border};font-weight:700;font-size:13px;'>heat {o['score']:.0f}</span>"
                f"</div>"
                f"<div style='color:{ui_style.TEXT_DIM};font-size:11px;margin-top:2px;'>"
                f"{(o.get('name') or '')[:32]} · {price_str} · {mc_str}</div>"
                f"<div style='color:{ui_style.TEXT};font-size:12px;margin-top:5px;'>{o.get('notes','')}</div>"
                f"</div>",
                unsafe_allow_html=True,
            )
        st.caption(":bulb: Type any of these into the **Thesis** tab for a full deep-dive, or the "
                   "**Charts** tab to chart it. Full ranked list is in the **Discover** tab.")

    # ---- Technical signals firing now (live across watchlist) ----
    from dk.indicators import signals as _sig
    st.markdown("### 📐 Technical signals firing now")
    st.caption("Live RSI, MACD crosses, golden/death crosses, Bollinger breakouts, 52-week breaks "
               "and volume surges across your watchlist.")
    _tech_rows = []
    for _s in equity_syms:
        try:
            _summ = _sig.summarize(_s)
        except Exception:
            continue
        for _g in _summ["signals"]:
            _tech_rows.append({"symbol": _s, **_g})
    if not _tech_rows:
        st.caption("No fresh technical signals on the watchlist right now — markets quiet or need a data refresh.")
    else:
        _tech_rows.sort(key=lambda x: (x["strength"], x["lean"] == "bull"), reverse=True)
        tcols = st.columns(2)
        for i, _g in enumerate(_tech_rows[:14]):
            border = (ui_style.BULL if _g["lean"] == "bull"
                      else ui_style.BEAR if _g["lean"] == "bear" else ui_style.NEUTRAL)
            icon = {"bull": "🟢", "bear": "🔴", "neutral": "⚪"}.get(_g["lean"], "")
            stars = "★" * _g["strength"]
            tcols[i % 2].markdown(
                f"<div style='background:{ui_style.CARD};border:1px solid {ui_style.BORDER};"
                f"border-left:4px solid {border};border-radius:9px;padding:9px 13px;margin:5px 0;'>"
                f"<span style='font-weight:800;color:{ui_style.TEXT};font-size:15px;'>{icon} {_g['symbol']}</span> "
                f"<span style='color:{border};font-size:11px;font-weight:600;'>{stars}</span>"
                f"<div style='color:{ui_style.TEXT};font-size:12.5px;margin-top:3px;'>{_g['label']}</div>"
                f"<div style='color:{ui_style.TEXT_DIM};font-size:11px;'>{_g['detail']}</div>"
                f"</div>",
                unsafe_allow_html=True,
            )
        st.caption(":bulb: ★ = signal strength. Green = bullish lean, red = bearish. "
                   "These also fire as `TECH_SIGNAL` alerts in the live feed below.")

    # ---- Watch-out risks ----
    risks = radar_mod.watchlist_risks(limit=4)
    if risks:
        st.markdown("### ⚠️ On your radar — caution")
        st.caption("Names where negative signals are converging — so you're not blindsided.")
        for r in risks:
            owned_tag = " :red-background[OWNED]" if r["owned"] else ""
            reasons_str = " · ".join(r["reasons"])
            st.markdown(
                f"<div style='background:{ui_style.CARD};border:1px solid {ui_style.BORDER};"
                f"border-left:4px solid {ui_style.BEAR};border-radius:10px;padding:10px 14px;margin:6px 0;'>"
                f"<span style='font-size:15px;font-weight:700;color:{ui_style.TEXT};'>{r['symbol']}{owned_tag}</span> "
                f"<span style='color:{ui_style.BEAR};font-size:12px;'>⚠️ {reasons_str}</span>"
                f"</div>",
                unsafe_allow_html=True,
            )

    # ---- The live briefing feed (prioritized signals) ----
    st.markdown("---")
    st.markdown("### 🔔 Live briefing — prioritized signals")
    cards = radar_mod.build_radar(hours=48, limit=40)
    if not cards:
        st.info("No signals in the last 48 hours yet. Click **Refresh data** in the toolbar.")
    else:
        # Group into urgency tiers
        hot = [c for c in cards if c["priority"] >= 85]
        notable = [c for c in cards if 60 <= c["priority"] < 85]
        fyi = [c for c in cards if c["priority"] < 60]

        def _render_card(card):
            owned_tag = " :green-background[OWNED]" if card["owned"] else (
                " :blue-background[watchlist]" if card["watchlist"] else "")
            link = (f" · <a href='{card['url']}' target='_blank' "
                    f"style='color:#4ea1ff;text-decoration:none;'>open →</a>"
                    if card.get("url") else "")
            score_ctx = (f" · <span style='color:#8b95ad;'>{card['score_context']}</span>"
                         if card.get("score_context") else "")
            st.markdown(
                f"<div style='background:{ui_style.CARD};border:1px solid {ui_style.BORDER};"
                f"border-radius:8px;padding:9px 13px;margin:5px 0;'>"
                f"<span style='font-size:15px;'>{card['icon']}</span> "
                f"<span style='color:{ui_style.ACCENT};font-weight:700;font-size:11px;"
                f"text-transform:uppercase;letter-spacing:0.5px;'>{card['category']}</span> "
                f"<span style='color:#8b95ad;font-size:11px;'>· {card['ts']}</span>"
                f"{owned_tag}"
                f"<div style='color:{ui_style.TEXT};font-size:13px;margin-top:3px;font-weight:600;'>"
                f"{card['headline']}</div>"
                f"<div style='color:#8b95ad;font-size:12px;margin-top:2px;'>"
                f"{card['why']}{score_ctx}{link}</div>"
                f"</div>",
                unsafe_allow_html=True,
            )

        if hot:
            st.markdown("#### 🔥 Hot — needs attention")
            for card in hot:
                _render_card(card)
        if notable:
            st.markdown("#### 👀 Notable")
            for card in notable:
                _render_card(card)
        if fyi:
            with st.expander(f"📌 FYI — {len(fyi)} lower-priority signals", expanded=False):
                for card in fyi:
                    _render_card(card)

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

        # ===== Theme score history =====
        st.markdown("---")
        st.markdown("##### :chart_with_upwards_trend: Theme score history")
        th_hist = q("""SELECT snapshot_ts, aggregate_score, avg_sentiment, avg_price_chg_1d
                       FROM theme_scores WHERE theme_id=? ORDER BY snapshot_ts ASC""",
                    (sel["id"],))
        if len(th_hist) >= 2:
            import plotly.graph_objects as go
            from plotly.subplots import make_subplots
            fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.7, 0.3],
                                vertical_spacing=0.06,
                                subplot_titles=("Aggregate score over time", "Avg sentiment"))
            fig.add_trace(go.Scatter(
                x=th_hist["snapshot_ts"], y=th_hist["aggregate_score"],
                mode="lines+markers", name="agg score",
                line=ui_style.LINE_PRIMARY,
                fill="tozeroy", fillcolor="rgba(0,212,170,0.10)",
            ), row=1, col=1)
            sent_colors = ["#00d4aa" if s and s > 0 else "#ff5d5d"
                            for s in th_hist["avg_sentiment"]]
            fig.add_trace(go.Bar(
                x=th_hist["snapshot_ts"], y=th_hist["avg_sentiment"],
                marker_color=sent_colors, name="sentiment",
            ), row=2, col=1)
            ui_style.style_fig(fig, height=380)
            fig.update_yaxes(range=[0, 100], title="score", row=1, col=1)
            fig.update_yaxes(title="sentiment", row=2, col=1)
            st.plotly_chart(fig, use_container_width=True)
            st.caption(f"Theme '{sel['name']}' has been tracked across **{len(th_hist)} snapshots**. "
                       "Each refresh adds one — the more you refresh, the richer this history gets.")
        else:
            st.caption(f"Only **{len(th_hist)} snapshot(s)** so far. Refresh the data a few times "
                       "to build a meaningful history for this theme.")

        # ===== Constituent comparison chart =====
        st.markdown("##### :crystal_ball: Constituent performance (30d)")
        cs_data = sel.get("constituents_scored", [])
        if cs_data:
            sym_list = [c_["symbol"] for c_ in cs_data]
            placeholders = ",".join("?" * len(sym_list))
            perf = q(f"""SELECT symbol, ts, close FROM prices
                         WHERE symbol IN ({placeholders})
                           AND ts >= date('now', '-30 days')
                         ORDER BY ts ASC""", tuple(sym_list))
            if not perf.empty:
                import plotly.graph_objects as go
                pivot = perf.pivot(index="ts", columns="symbol", values="close").dropna(how="all")
                # Normalize each to 100 at start
                normalized = pivot.div(pivot.iloc[0]).mul(100) - 100  # % change from start
                fig = go.Figure()
                palette = [ui_style.ACCENT, ui_style.ACCENT_2, "#b66dff", ui_style.WARN,
                           ui_style.BEAR, "#06d6a0", "#ffd166", "#ef476f", "#118ab2",
                           "#fb5607", "#8338ec", "#3a86ff", "#06ffa5"]
                for i, sym in enumerate(normalized.columns):
                    fig.add_trace(go.Scatter(
                        x=normalized.index, y=normalized[sym], mode="lines",
                        name=sym, line=dict(color=palette[i % len(palette)], width=1.8),
                    ))
                ui_style.style_fig(fig, height=380)
                fig.update_yaxes(title="% change vs 30d start", ticksuffix="%")
                st.plotly_chart(fig, use_container_width=True)
                st.caption("Each constituent normalized to 0% at start of window. Lines diverging "
                           "from each other = idiosyncratic; moving together = sector-wide.")
            else:
                st.caption("Not enough price history yet for the constituents.")

        # ===== Catalyst timeline =====
        st.markdown("##### :scroll: Catalyst timeline — what's driving this theme")
        timeline = q("""SELECT symbol, title, url, source, sentiment, published, fetched_at
                        FROM news
                        WHERE symbol IN ({})
                          AND sentiment IS NOT NULL
                          AND fetched_at >= datetime('now', '-30 days')
                        ORDER BY fetched_at DESC
                        LIMIT 30""".format(
                            ",".join(f"'{s}'" for s in sym_list) if sym_list else "''")
                     )
        if timeline.empty:
            st.caption("No recent news catalysts captured for this theme's constituents in the last 30 days.")
        else:
            # Group by date
            timeline["date"] = pd.to_datetime(timeline["fetched_at"]).dt.date.astype(str)
            for date_val, group in timeline.groupby("date", sort=False):
                avg_tone = group["sentiment"].mean()
                tone_color = "green" if avg_tone > 0.1 else ("red" if avg_tone < -0.1 else "gray")
                st.markdown(
                    f"<div style='color:#8b95ad;font-size:11px;font-weight:700;"
                    f"letter-spacing:1.5px;text-transform:uppercase;margin:14px 0 6px 0;'>"
                    f"📅 {date_val} · avg tone <span style='color:#{ {'green':'00d4aa','red':'ff5d5d','gray':'8b95ad'}[tone_color] }'>"
                    f"{avg_tone:+.2f}</span> · {len(group)} headlines"
                    f"</div>",
                    unsafe_allow_html=True,
                )
                for _, n in group.iterrows():
                    tone = "🟢" if (n["sentiment"] or 0) > 0.05 else (
                        "🔴" if (n["sentiment"] or 0) < -0.05 else "⚪"
                    )
                    st.markdown(
                        f"- {tone} `{n['symbol']}` **[{n['title']}]({n['url']})**  \n"
                        f"  <small>{n['source']} · score {n['sentiment']:+.2f}</small>",
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
        chart_studio.render(th_sym, key=f"thesis_studio_{th_sym}", default_period="6M")

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
        chart_studio.render(focus, key=f"watch_studio_{focus}", default_period="3M")

with tab_sentiment:
    sent_view = st.radio(
        "View", ["Market sentiment", "Per-ticker sentiment"],
        horizontal=True, label_visibility="collapsed", key="sent_view_pick",
    )

    # ===== MARKET SENTIMENT (Fear & Greed style composite) =====
    if sent_view == "Market sentiment":
        from dk.sentiment import market as market_sent

        latest = q("""SELECT snapshot_ts, composite, label, components_json
                      FROM market_sentiment ORDER BY snapshot_ts DESC LIMIT 1""")
        if latest.empty:
            st.info("Market sentiment hasn't been computed yet. Click **Refresh data** "
                    "in the toolbar above (or click the button below).")
            if st.button("Compute market sentiment now"):
                with st.spinner("Computing market sentiment composite from VIX, bonds, breadth, news..."):
                    market_sent.persist_snapshot()
                st.rerun()
        else:
            row = latest.iloc[0]
            comp = float(row["composite"])
            label = row["label"]
            ts = row["snapshot_ts"]
            import json as _json
            try:
                components = _json.loads(row["components_json"] or "{}")
            except Exception:
                components = {}

            # Big gauge card
            color = (ui_style.BULL if comp >= 60 else
                     ui_style.BEAR if comp <= 40 else ui_style.WARN)
            st.markdown(
                f"<div style='background:{ui_style.CARD};border:1px solid {ui_style.BORDER};"
                f"border-radius:14px;padding:24px;text-align:center;margin-bottom:14px;'>"
                f"<div style='color:{ui_style.TEXT_DIM};font-size:11px;font-weight:700;"
                f"letter-spacing:1.6px;text-transform:uppercase;margin-bottom:8px;'>Market Mood</div>"
                f"<div style='font-size:72px;font-weight:800;color:{color};line-height:1;'>{comp:.0f}</div>"
                f"<div style='font-size:24px;color:{color};font-weight:700;margin-top:8px;'>{label}</div>"
                f"<div style='color:{ui_style.TEXT_DIM};font-size:11px;margin-top:10px;'>"
                f"0 = Extreme Fear · 50 = Neutral · 100 = Extreme Greed</div>"
                f"<div style='color:{ui_style.TEXT_DIM};font-size:11px;margin-top:4px;'>"
                f"as of {ts}</div>"
                f"</div>",
                unsafe_allow_html=True,
            )

            # Component breakdown
            st.markdown("#### Composite components")
            comp_rows = []
            comp_labels = {
                "vix": "VIX inverted (volatility)",
                "safe_haven": "SPY vs TLT 20d (safe haven)",
                "junk_demand": "HYG vs LQD 20d (risk appetite)",
                "spy_momentum": "SPY vs 125d MA (momentum)",
                "breadth_watchlist": "% watchlist above 50d SMA",
                "news_breadth_24h": "% positive news (24h)",
            }
            for key, lbl in comp_labels.items():
                v = components.get(key)
                if v is None:
                    comp_rows.append({"Indicator": lbl, "Score": "n/a", "_v": 50})
                else:
                    comp_rows.append({"Indicator": lbl, "Score": f"{v:.1f}", "_v": float(v)})
            comp_df = pd.DataFrame(comp_rows)
            st.dataframe(
                comp_df[["Indicator", "_v", "Score"]].rename(columns={"_v": "level"}),
                use_container_width=True, hide_index=True,
                column_config={
                    "level": st.column_config.ProgressColumn(
                        "level", min_value=0, max_value=100, format="%.0f"),
                },
            )
            st.caption("Each component is normalized 0–100 (0 = extreme fear, 100 = extreme greed) "
                       "then averaged into the composite.")

            # History chart
            hist = q("""SELECT snapshot_ts, composite, label FROM market_sentiment
                        ORDER BY snapshot_ts ASC""")
            if len(hist) >= 2:
                st.markdown("#### Market mood history")
                import plotly.graph_objects as go
                fig = go.Figure()
                fig.add_trace(go.Scatter(
                    x=hist["snapshot_ts"], y=hist["composite"],
                    mode="lines+markers", name="composite",
                    line=ui_style.LINE_PRIMARY,
                    fill="tozeroy", fillcolor="rgba(0,212,170,0.10)",
                ))
                # Zone lines
                for level, txt, clr in [(80, "Extreme Greed", ui_style.BULL),
                                          (20, "Extreme Fear", ui_style.BEAR)]:
                    fig.add_hline(y=level, line=dict(color=clr, width=1, dash="dot"),
                                  annotation_text=txt, annotation_position="right",
                                  annotation_font_color=clr)
                ui_style.style_fig(fig, height=320)
                fig.update_yaxes(range=[0, 100])
                st.plotly_chart(fig, use_container_width=True)

            # Aggregate market news mood
            st.markdown("#### Aggregate news tone (last 24h)")
            agg = q("""SELECT
                          ROUND(AVG(sentiment), 3) AS avg_sent,
                          COUNT(*) AS articles,
                          SUM(CASE WHEN sentiment > 0.05 THEN 1 ELSE 0 END) AS bull,
                          SUM(CASE WHEN sentiment < -0.05 THEN 1 ELSE 0 END) AS bear
                       FROM news WHERE sentiment IS NOT NULL
                         AND fetched_at >= datetime('now', '-1 day')""")
            if not agg.empty and agg.iloc[0]["articles"]:
                a = agg.iloc[0]
                ac1, ac2, ac3, ac4 = st.columns(4)
                ac1.metric("Avg sentiment", f"{a['avg_sent']:+.3f}")
                ac2.metric("Articles", f"{int(a['articles']):,}")
                ac3.metric("Bullish", f"{int(a['bull']):,}",
                            f"{a['bull']/a['articles']*100:.0f}%")
                ac4.metric("Bearish", f"{int(a['bear']):,}",
                            f"{a['bear']/a['articles']*100:.0f}%")

    # ===== PER-TICKER SENTIMENT (original view) =====
    else:
        st.subheader("Per-ticker sentiment (last 24h)")
        df = q("""SELECT symbol, AVG(sentiment) AS avg_sentiment, COUNT(*) AS articles
                  FROM news
                  WHERE symbol IS NOT NULL AND sentiment IS NOT NULL
                    AND fetched_at >= datetime('now', '-1 day')
                  GROUP BY symbol ORDER BY ABS(AVG(sentiment)) DESC""")
        if df.empty:
            st.info("No scored news yet — refresh from the toolbar.")
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
    # ===== Top metrics: source count, last fetch, breaking count =====
    src_count_df = q("SELECT COUNT(DISTINCT source) AS n FROM news")
    last_fetch_df = q("SELECT MAX(fetched_at) AS last FROM news")
    breaking_count_df = q("""SELECT COUNT(*) AS n FROM news
                              WHERE is_breaking=1
                                AND fetched_at >= datetime('now', '-24 hours')""")

    nc1, nc2, nc3, nc4 = st.columns(4)
    nc1.metric("Sources covered", int(src_count_df.iloc[0]["n"] or 0))
    nc2.metric("Last fetch", str(last_fetch_df.iloc[0]["last"] or "—")[:16])
    nc3.metric("⚡ Breaking (24h)", int(breaking_count_df.iloc[0]["n"] or 0))
    art_24h = q("SELECT COUNT(*) AS n FROM news WHERE fetched_at >= datetime('now', '-24 hours')")
    nc4.metric("Articles (24h)", int(art_24h.iloc[0]["n"] or 0))

    # ===== Power Players panel =====
    from dk.sources import people_tracker
    st.markdown("---")
    st.markdown("### 👤 Power Players (last 24h)")
    st.caption("Tracked figures with market pull. Edit `config/people.yaml` to add/remove.")

    # Load full people config so we can render X links
    import yaml as _yaml
    _people_path = (__import__("dk.config", fromlist=["CONFIG_DIR"])).CONFIG_DIR / "people.yaml"
    _people_cfg = []
    if _people_path.exists():
        with open(_people_path, "r", encoding="utf-8") as _f:
            _people_cfg = (_yaml.safe_load(_f) or {}).get("people") or []
    _people_by_name = {p["name"]: p for p in _people_cfg}

    mentions = people_tracker.person_mention_counts(hours=24)
    if not mentions:
        st.info("No tracked figures mentioned in news yet — refresh data above.")
    else:
        pp_df = pd.DataFrame(mentions)

        def _weight_label(w):
            return "🔴 Heavy" if w >= 3 else ("🟠 Medium" if w == 2 else "⚪ Low")

        def _x_link(name):
            p = _people_by_name.get(name) or {}
            h = p.get("x_handle")
            return f"https://x.com/{h}" if h else None

        pp_df["pull"] = pp_df["weight"].apply(_weight_label)
        pp_df["X profile"] = pp_df["name"].apply(_x_link)
        st.dataframe(
            pp_df[["pull", "name", "role", "mentions", "avg_sentiment", "X profile", "affects"]],
            use_container_width=True, hide_index=True,
            column_config={
                "mentions": st.column_config.NumberColumn("mentions (24h)", format="%d"),
                "avg_sentiment": st.column_config.NumberColumn("avg sentiment", format="%+.2f"),
                "X profile": st.column_config.LinkColumn("X profile", display_text="@view"),
            },
        )
        st.caption(":bulb: When any tracked figure speaks/posts/announces something with a breaking-keyword "
                   "match or strong sentiment, a **PERSON_ACTIVITY** alert fires in the Alerts tab.")

    # ===== Recent X posts panel =====
    st.markdown("#### 🐦 Recent X posts from tracked figures")
    x_posts = q("""SELECT fetched_at, source, title, url, sentiment
                   FROM news WHERE source LIKE 'X:%'
                     AND fetched_at >= datetime('now', '-48 hours')
                   ORDER BY fetched_at DESC LIMIT 30""")
    if x_posts.empty:
        st.info("No X posts captured in the last 48 hours. Nitter/RSSHub instances may be "
                "rate-limited or down — use the X profile links above to check manually. "
                "(Newsworthy posts still surface via news coverage even when RSS is unavailable.)")
        # Show all the direct profile links as a fallback
        x_handles = [(p["name"], p.get("x_handle")) for p in _people_cfg if p.get("x_handle")]
        if x_handles:
            cols = st.columns(4)
            for i, (n, h) in enumerate(x_handles):
                cols[i % 4].markdown(f"[**{n}** @{h}](https://x.com/{h})")
    else:
        for _, row in x_posts.iterrows():
            tone = senti_label(row["sentiment"]) if row["sentiment"] is not None else "·"
            color = "green" if tone == "+" else ("red" if tone == "-" else "gray")
            handle = row["source"].replace("X:", "").lstrip("@")
            st.markdown(
                f"<div style='background:rgba(78,161,255,0.06);border-left:3px solid #4ea1ff;"
                f"padding:8px 12px;margin:5px 0;border-radius:6px;'>"
                f"<span style='color:#4ea1ff;font-weight:700;font-size:11px;'>🐦 {handle}</span> "
                f"<span style='color:#{ {'green':'00d4aa','red':'ff5d5d','gray':'8b95ad'}[color] }'>"
                f"{tone}</span> "
                f"<a href='{row['url']}' style='color:#e8ecf4;text-decoration:none;' target='_blank'>"
                f"{row['title']}</a>"
                f"<div style='color:#8b95ad;font-size:11px;margin-top:3px;'>"
                f"{row['fetched_at']}</div>"
                f"</div>",
                unsafe_allow_html=True,
            )

    # ===== Breaking news panel =====
    st.markdown("---")
    st.markdown("### ⚡ Breaking news (high-impact, last 24h)")
    st.caption("Auto-flagged from keywords: M&A, FDA approvals, guidance changes, contract wins, "
               "bankruptcies, executive changes, regulatory actions, ETF approvals, exploits, etc.")
    breaking = q("""SELECT published, fetched_at, source, region, title, url, symbol, sentiment
                    FROM news WHERE is_breaking=1
                      AND fetched_at >= datetime('now', '-24 hours')
                    ORDER BY fetched_at DESC LIMIT 30""")
    if breaking.empty:
        st.info("No breaking news flagged in the last 24h.")
    else:
        for _, row in breaking.iterrows():
            tag = f"`{row['symbol']}`" if row['symbol'] else f"_{row['region'] or 'GLOBAL'}_"
            tone = senti_label(row["sentiment"]) if row["sentiment"] is not None else "·"
            color = "green" if tone == "+" else ("red" if tone == "-" else "gray")
            sentiment_str = f"score {row['sentiment']:+.2f}" if row["sentiment"] is not None else ""
            st.markdown(
                f"<div style='background:rgba(255,181,71,0.06);border-left:3px solid #ffb547;"
                f"padding:10px 14px;margin:6px 0;border-radius:6px;'>"
                f"<span style='color:#ffb547;font-weight:700;font-size:11px;'>⚡ BREAKING</span> "
                f"<span style='color:#{ {'green':'00d4aa','red':'ff5d5d','gray':'8b95ad'}[color] }'>"
                f"{tone}</span> {tag} "
                f"<a href='{row['url']}' style='color:#e8ecf4;text-decoration:none;font-weight:600;' target='_blank'>"
                f"{row['title']}</a>"
                f"<div style='color:#8b95ad;font-size:11px;margin-top:3px;'>"
                f"{row['source']} · {row['fetched_at']} · {sentiment_str}</div>"
                f"</div>",
                unsafe_allow_html=True,
            )

    # ===== Filters + full feed =====
    st.markdown("---")
    st.markdown("### Full news feed")

    # Source filter + sentiment filter
    src_list_df = q("SELECT DISTINCT source FROM news ORDER BY source")
    all_sources = src_list_df["source"].dropna().tolist() if not src_list_df.empty else []
    fcol1, fcol2, fcol3 = st.columns([2, 1, 1])
    selected_sources = fcol1.multiselect(
        "Filter by source", all_sources,
        placeholder="All sources" if all_sources else "No sources yet",
        key="news_src_filter",
    )
    sentiment_filter = fcol2.selectbox(
        "Sentiment", ["Any", "Positive", "Negative", "Neutral"], key="news_sent_filter")
    breaking_only = fcol3.checkbox("⚡ Breaking only", key="news_breaking_only")

    # Build query
    placeholders = ",".join("?" * len(selected_regions)) if selected_regions else "''"
    where_clauses = []
    params = []

    if focus != "(all)":
        where_clauses.append("symbol = ?")
        params.append(focus)
    else:
        where_clauses.append(f"(region IN ({placeholders}) OR symbol IS NOT NULL)")
        params.extend(selected_regions)

    if selected_sources:
        src_placeholders = ",".join("?" * len(selected_sources))
        where_clauses.append(f"source IN ({src_placeholders})")
        params.extend(selected_sources)

    if sentiment_filter == "Positive":
        where_clauses.append("sentiment > 0.05")
    elif sentiment_filter == "Negative":
        where_clauses.append("sentiment < -0.05")
    elif sentiment_filter == "Neutral":
        where_clauses.append("(sentiment BETWEEN -0.05 AND 0.05 OR sentiment IS NULL)")

    if breaking_only:
        where_clauses.append("is_breaking = 1")

    where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"
    sql = f"""SELECT published, fetched_at, source, region, title, url, symbol, sentiment, is_breaking
              FROM news WHERE {where_sql}
              ORDER BY fetched_at DESC LIMIT 200"""

    df = q(sql, tuple(params))
    if df.empty:
        st.info("No matching news. Try widening filters or click **Refresh data**.")
    else:
        st.caption(f":bulb: Showing {len(df)} articles. Use filters above to narrow.")
        for _, row in df.iterrows():
            tag = f"`{row['symbol']}`" if row['symbol'] else f"_{row['region'] or 'GLOBAL'}_"
            tone = senti_label(row["sentiment"]) if row["sentiment"] is not None else "·"
            color = "green" if tone == "+" else ("red" if tone == "-" else "gray")
            breaking_badge = " :orange-background[⚡ BREAKING]" if row.get("is_breaking") else ""
            sentiment_str = (f" · score {row['sentiment']:+.2f}"
                              if row["sentiment"] is not None else "")
            st.markdown(
                f"- :{color}[**{tone}**] {tag}{breaking_badge} **[{row['title']}]({row['url']})**  \n"
                f"  <small>{row['source']} · {row['fetched_at']}{sentiment_str}</small>",
                unsafe_allow_html=True,
            )

with tab_earnings:
    st.subheader("📅 Earnings center")

    def _fmt_money(v):
        try:
            v = float(v)
        except (TypeError, ValueError):
            return "—"
        if v != v:
            return "—"
        sign = "-" if v < 0 else ""
        a = abs(v)
        if a >= 1e9:
            return f"{sign}${a/1e9:.2f}B"
        if a >= 1e6:
            return f"{sign}${a/1e6:.1f}M"
        return f"{sign}${a:,.0f}"

    def _fmt_eps(v):
        try:
            return f"${float(v):.2f}"
        except (TypeError, ValueError):
            return "—"

    # ---- Upcoming earnings ----
    st.markdown("#### Upcoming reports")
    up = q("""SELECT symbol, report_date, eps_estimate, revenue_estimate
              FROM earnings WHERE report_date >= date('now')
              ORDER BY report_date ASC LIMIT 100""")
    if up.empty:
        st.info("No upcoming earnings on file. Add `FINNHUB_KEY` for the full market calendar; "
                "watchlist dates come from yfinance.")
    else:
        up = up.copy()
        up["days_out"] = (pd.to_datetime(up["report_date"], errors="coerce")
                          - pd.Timestamp.now().normalize()).dt.days
        up["EPS est"] = up["eps_estimate"].apply(_fmt_eps)
        up["Revenue est"] = up["revenue_estimate"].apply(_fmt_money)
        view = up[["symbol", "report_date", "days_out", "EPS est", "Revenue est"]]
        clickable_table(view, key="earn_upcoming", column_config={
            "days_out": st.column_config.NumberColumn("days out", format="%d"),
        })
        st.caption(":bulb: Click a row for a chart preview. EPS/revenue are consensus estimates.")

    # ---- Recently reported (with surprises) ----
    st.markdown("#### Recently reported — beats & misses")
    rep = q("""SELECT symbol, report_date, eps_estimate, eps_actual,
                      revenue_estimate, revenue_actual
               FROM earnings
               WHERE eps_actual IS NOT NULL AND report_date >= date('now', '-45 days')
               ORDER BY report_date DESC LIMIT 50""")
    if rep.empty:
        st.caption("No reported results captured yet (needs `FINNHUB_KEY` for actuals).")
    else:
        rep = rep.copy()

        def _eps_surprise(r):
            try:
                est, act = float(r["eps_estimate"]), float(r["eps_actual"])
                if est == 0:
                    return None
                return (act - est) / abs(est) * 100
            except (TypeError, ValueError):
                return None

        rep["EPS est"] = rep["eps_estimate"].apply(_fmt_eps)
        rep["EPS act"] = rep["eps_actual"].apply(_fmt_eps)
        rep["surprise"] = rep.apply(_eps_surprise, axis=1)
        rep["Rev est"] = rep["revenue_estimate"].apply(_fmt_money)
        rep["Rev act"] = rep["revenue_actual"].apply(_fmt_money)
        rep["result"] = rep["surprise"].apply(
            lambda s: "🟢 beat" if (s or 0) > 1 else ("🔴 miss" if (s or 0) < -1 else "≈ inline")
            if s is not None else "—")
        view = rep[["symbol", "report_date", "result", "EPS est", "EPS act",
                    "surprise", "Rev est", "Rev act"]]
        st.dataframe(view, use_container_width=True, hide_index=True, column_config={
            "surprise": st.column_config.NumberColumn("EPS surprise", format="%+.1f%%"),
        })

    # ---- Earnings-related news ----
    st.markdown("#### Earnings news & expectations")
    enews = q("""SELECT published, fetched_at, source, title, url, symbol, sentiment
                 FROM news
                 WHERE (lower(title) LIKE '%earnings%' OR lower(title) LIKE '%revenue%'
                        OR lower(title) LIKE '%guidance%' OR lower(title) LIKE '%beats%'
                        OR lower(title) LIKE '%misses%' OR lower(title) LIKE '%quarterly%'
                        OR lower(title) LIKE '%eps%' OR lower(title) LIKE '%forecast%')
                 ORDER BY fetched_at DESC LIMIT 25""")
    if enews.empty:
        st.caption("No earnings-related headlines captured yet — refresh data.")
    else:
        for _, row in enews.iterrows():
            tone = senti_label(row["sentiment"]) if row["sentiment"] is not None else "·"
            color = "green" if tone == "+" else ("red" if tone == "-" else "gray")
            tag = f"`{row['symbol']}`" if row["symbol"] else ""
            st.markdown(
                f"- :{color}[**{tone}**] {tag} **[{row['title']}]({row['url']})**  \n"
                f"  <small>{row['source']} · {row['fetched_at']}</small>",
                unsafe_allow_html=True,
            )

with tab_calendar:
    import calendar as _calmod
    from datetime import date as _date

    st.subheader("🗓️ Market calendar")

    # Month navigation
    nav1, nav2, nav3, nav4 = st.columns([1, 1, 1, 4])
    if nav1.button("◀ Prev", key="cal_prev"):
        st.session_state["_cal_offset"] = st.session_state.get("_cal_offset", 0) - 1
    if nav2.button("Today", key="cal_today"):
        st.session_state["_cal_offset"] = 0
    if nav3.button("Next ▶", key="cal_next"):
        st.session_state["_cal_offset"] = st.session_state.get("_cal_offset", 0) + 1

    _offset = st.session_state.get("_cal_offset", 0)
    _today = _date.today()
    _mi = _today.month - 1 + _offset
    _year = _today.year + _mi // 12
    _month = _mi % 12 + 1
    nav4.markdown(f"### {_calmod.month_name[_month]} {_year}")

    # Gather events for this month
    _mstart = _date(_year, _month, 1)
    _last_day = _calmod.monthrange(_year, _month)[1]
    _mend = _date(_year, _month, _last_day)
    events_by_day: dict[str, list[dict]] = {}

    def _add_ev(dstr, label, color):
        events_by_day.setdefault(dstr, []).append({"label": label, "color": color})

    # Earnings
    _earn = q("""SELECT symbol, report_date FROM earnings
                 WHERE report_date BETWEEN ? AND ?""",
              (_mstart.isoformat(), _mend.isoformat()))
    for _, r in _earn.iterrows():
        _add_ev(str(r["report_date"])[:10], f"📊 {r['symbol']}", ui_style.ACCENT_2)
    # Macro events
    _mac = q("""SELECT event_date, title, importance FROM macro_events
                WHERE event_date BETWEEN ? AND ?""",
             (_mstart.isoformat(), _mend.isoformat()))
    for _, r in _mac.iterrows():
        col = ui_style.WARN if (r["importance"] or 0) >= 2 else ui_style.NEUTRAL
        _add_ev(str(r["event_date"])[:10], f"🌐 {str(r['title'])[:22]}", col)
    # Curated events
    try:
        from dk.sources import events_calendar as _ec
        for ev in _ec.load_events():
            ed = str(ev.get("date"))
            if _mstart.isoformat() <= ed <= _mend.isoformat():
                _add_ev(ed, f"📣 {str(ev.get('title'))[:22]}", ui_style.BULL)
    except Exception:
        pass

    # Build the grid (Sunday-first)
    _calmod.setfirstweekday(_calmod.SUNDAY)
    weeks = _calmod.monthcalendar(_year, _month)
    dow = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
    html = ["<table style='width:100%;border-collapse:collapse;table-layout:fixed;'>"]
    html.append("<tr>" + "".join(
        f"<th style='padding:6px;color:{ui_style.TEXT_DIM};font-size:11px;"
        f"text-transform:uppercase;letter-spacing:1px;border-bottom:1px solid {ui_style.BORDER};'>{d}</th>"
        for d in dow) + "</tr>")
    for week in weeks:
        html.append("<tr>")
        for day in week:
            if day == 0:
                html.append(f"<td style='background:#0a0e16;border:1px solid {ui_style.BORDER};height:96px;'></td>")
                continue
            dstr = _date(_year, _month, day).isoformat()
            is_today = (dstr == _today.isoformat())
            evs = events_by_day.get(dstr, [])
            chips = "".join(
                f"<div style='background:{e['color']}22;color:{e['color']};border-radius:4px;"
                f"padding:1px 4px;margin:1px 0;font-size:10px;white-space:nowrap;overflow:hidden;"
                f"text-overflow:ellipsis;'>{e['label']}</div>"
                for e in evs[:4])
            more = (f"<div style='color:{ui_style.TEXT_DIM};font-size:9px;'>+{len(evs)-4} more</div>"
                    if len(evs) > 4 else "")
            daynum_color = ui_style.ACCENT if is_today else ui_style.TEXT
            border = (f"2px solid {ui_style.ACCENT}" if is_today else f"1px solid {ui_style.BORDER}")
            html.append(
                f"<td style='background:{ui_style.CARD};border:{border};height:96px;"
                f"vertical-align:top;padding:4px;'>"
                f"<div style='color:{daynum_color};font-weight:700;font-size:12px;'>{day}</div>"
                f"{chips}{more}</td>")
        html.append("</tr>")
    html.append("</table>")
    st.markdown("".join(html), unsafe_allow_html=True)
    st.caption("📊 earnings · 🌐 macro event · 📣 known event. Use Prev/Next to change month.")

    # IPOs below the grid
    st.markdown("---")
    st.subheader("Upcoming IPOs")
    ipos = q("""SELECT expected_date, symbol, name, price_range, exchange, source
                FROM ipos WHERE expected_date >= date('now', '-30 days')
                ORDER BY expected_date DESC LIMIT 100""")
    if ipos.empty:
        st.info("No IPO data yet. Add a `FINNHUB_KEY` for the Finnhub IPO calendar; "
                "SEC S-1 filings come in via RSS regardless.")
    else:
        st.dataframe(ipos, use_container_width=True, hide_index=True)

with tab_crypto:
    st.subheader("🪙 Crypto — top 25 by market cap")
    from dk.sources import leaderboards as _lbc

    @st.cache_data(ttl=600, show_spinner=False)
    def _top25_crypto():
        return _lbc.top_crypto(25)

    if st.button("↻ Refresh crypto", key="crypto_refresh"):
        st.cache_data.clear()
        st.rerun()

    rows = _top25_crypto()
    if not rows:
        st.info("Couldn't load crypto right now — click Refresh, or check back shortly.")
    else:
        cdf = pd.DataFrame(rows)
        cdf["mcap_B"] = (cdf["market_cap"] / 1e9).round(2)
        cdf["vol_B"] = (cdf["volume"] / 1e9).round(2)
        view = cdf[["rank", "symbol", "name", "price", "change_24h", "change_7d", "mcap_B", "vol_B"]]
        st.dataframe(
            view, use_container_width=True, hide_index=True, column_config={
                "rank": st.column_config.NumberColumn("#", format="%d"),
                "price": st.column_config.NumberColumn("price", format="$%.4f"),
                "change_24h": st.column_config.NumberColumn("24h", format="%+.2f%%"),
                "change_7d": st.column_config.NumberColumn("7d", format="%+.2f%%"),
                "mcap_B": st.column_config.NumberColumn("mkt cap ($B)", format="%.2f"),
                "vol_B": st.column_config.NumberColumn("24h vol ($B)", format="%.2f"),
            },
        )
        st.caption("Live top 25 from CoinGecko, cached ~10 min.")

    # Watchlist crypto (from poller) below the top 25
    st.markdown("---")
    st.markdown("#### Your watchlist crypto")
    df = q("""SELECT cp.symbol, cp.ts, cp.price_usd, cp.change_24h_pct, cp.vol_24h, cp.market_cap
              FROM crypto_prices cp
              INNER JOIN (SELECT symbol, MAX(ts) m FROM crypto_prices GROUP BY symbol) lat
                ON cp.symbol=lat.symbol AND cp.ts=lat.m
              ORDER BY cp.symbol""")
    if df.empty:
        st.caption("No watchlist crypto data yet — refresh data.")
    else:
        clickable_table(
            df.round({"price_usd": 2, "change_24h_pct": 2}),
            key="crypto_table",
            column_config={"change_24h_pct": st.column_config.NumberColumn("24h chg", format="%+.2f%%")},
        )

# ---- Trademark footer (signature configurable in config/watchlist.yaml -> branding.signature) ----
_signature = (wl.get("branding") or {}).get("signature", "DK Investing™")
ui_style.footer(_signature)
