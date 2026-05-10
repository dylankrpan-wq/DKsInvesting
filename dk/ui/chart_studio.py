"""Chart Studio — full-featured chart component.

Controls:
  - Period: 1d / 5d / 1mo / 3mo / 6mo / 1y / 2y / 5y / max
  - Interval: 1m / 5m / 15m / 1h / 1d / 1wk / 1mo
  - Style: Candles / OHLC / Line / Area
  - Overlays: SMA20/50/200, EMA12/26, Bollinger Bands
  - Panels: Volume, RSI(14), MACD(12,26,9)
  - POV: Price | +Sentiment | +News markers | +Earnings | vs SPY (relative)
  - Source: yfinance (DK) | TradingView (live embed)
"""
from __future__ import annotations
import sqlite3
import numpy as np
import pandas as pd
import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from dk.config import DB_PATH
from dk.ui import style as ui_style


# yfinance interval restrictions for periods. We expose only sensible combos.
PERIOD_INTERVALS = {
    "1d":  ["1m", "5m", "15m", "1h"],
    "5d":  ["5m", "15m", "30m", "1h", "1d"],
    "1mo": ["30m", "1h", "1d"],
    "3mo": ["1h", "1d", "1wk"],
    "6mo": ["1d", "1wk"],
    "1y":  ["1d", "1wk"],
    "2y":  ["1d", "1wk", "1mo"],
    "5y":  ["1wk", "1mo"],
    "max": ["1wk", "1mo"],
}
DEFAULT_INTERVAL = {
    "1d": "5m", "5d": "1h", "1mo": "1h", "3mo": "1d", "6mo": "1d",
    "1y": "1d", "2y": "1d", "5y": "1wk", "max": "1mo",
}


@st.cache_data(ttl=300, show_spinner=False)
def _fetch(symbol: str, period: str, interval: str) -> pd.DataFrame:
    import yfinance as yf
    try:
        df = yf.Ticker(symbol).history(period=period, interval=interval, auto_adjust=False)
        if df.empty:
            return df
        df = df.reset_index()
        # yfinance uses 'Date' for daily, 'Datetime' for intraday
        ts_col = "Datetime" if "Datetime" in df.columns else "Date"
        df = df.rename(columns={ts_col: "ts"})
        return df
    except Exception as e:
        print(f"[chart_studio] {symbol} {period}/{interval}: {e}")
        return pd.DataFrame()


def _sma(arr: np.ndarray, n: int) -> np.ndarray:
    if len(arr) < n:
        return np.full_like(arr, np.nan, dtype=float)
    cum = np.cumsum(np.insert(arr.astype(float), 0, 0.0))
    return np.concatenate([np.full(n - 1, np.nan), (cum[n:] - cum[:-n]) / n])


def _ema(arr: np.ndarray, n: int) -> np.ndarray:
    arr = arr.astype(float)
    if len(arr) == 0:
        return arr
    alpha = 2.0 / (n + 1)
    out = np.empty_like(arr)
    out[0] = arr[0]
    for i in range(1, len(arr)):
        out[i] = alpha * arr[i] + (1 - alpha) * out[i - 1]
    return out


def _rsi(arr: np.ndarray, n: int = 14) -> np.ndarray:
    arr = arr.astype(float)
    if len(arr) < n + 1:
        return np.full_like(arr, np.nan, dtype=float)
    deltas = np.diff(arr, prepend=arr[0])
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    avg_gain = np.full_like(arr, np.nan)
    avg_loss = np.full_like(arr, np.nan)
    avg_gain[n] = gains[1:n + 1].mean()
    avg_loss[n] = losses[1:n + 1].mean()
    for i in range(n + 1, len(arr)):
        avg_gain[i] = (avg_gain[i - 1] * (n - 1) + gains[i]) / n
        avg_loss[i] = (avg_loss[i - 1] * (n - 1) + losses[i]) / n
    rs = np.where(avg_loss == 0, np.inf, avg_gain / avg_loss)
    return 100.0 - (100.0 / (1.0 + rs))


def _macd(arr: np.ndarray, fast: int = 12, slow: int = 26, sig: int = 9):
    line = _ema(arr, fast) - _ema(arr, slow)
    signal = _ema(line, sig)
    return line, signal, line - signal


def _bbands(arr: np.ndarray, n: int = 20, k: float = 2.0):
    arr = arr.astype(float)
    if len(arr) < n:
        nan = np.full_like(arr, np.nan, dtype=float)
        return nan, nan, nan
    mid = _sma(arr, n)
    sd = pd.Series(arr).rolling(n, min_periods=n).std(ddof=0).values
    return mid, mid + k * sd, mid - k * sd


def _news_density(symbol: str, ts_index: pd.DatetimeIndex) -> pd.DataFrame | None:
    with sqlite3.connect(DB_PATH) as c:
        df = pd.read_sql_query(
            """SELECT fetched_at, sentiment FROM news
               WHERE symbol=? AND sentiment IS NOT NULL
               ORDER BY fetched_at""",
            c, params=(symbol,),
        )
    if df.empty:
        return None
    df["ts"] = pd.to_datetime(df["fetched_at"], errors="coerce", utc=True).dt.tz_localize(None)
    df = df.dropna(subset=["ts"])
    return df


def _earnings_dates(symbol: str) -> list[str]:
    with sqlite3.connect(DB_PATH) as c:
        rows = c.execute(
            "SELECT report_date FROM earnings WHERE symbol=? AND report_date >= date('now', '-2 years')",
            (symbol,),
        ).fetchall()
    return [r[0][:10] for r in rows if r and r[0]]


def _save_preset(name: str, symbol: str, settings: dict) -> None:
    import json, sqlite3
    with sqlite3.connect(DB_PATH) as c:
        c.execute("""INSERT OR REPLACE INTO chart_presets (name, symbol, settings_json)
                     VALUES (?, ?, ?)""",
                  (name.strip(), symbol, json.dumps(settings)))
        c.commit()


def _load_presets() -> list[dict]:
    import sqlite3
    with sqlite3.connect(DB_PATH) as c:
        c.row_factory = sqlite3.Row
        rows = c.execute(
            "SELECT id, name, symbol, settings_json, created_at FROM chart_presets ORDER BY created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def _delete_preset(preset_id: int) -> None:
    import sqlite3
    with sqlite3.connect(DB_PATH) as c:
        c.execute("DELETE FROM chart_presets WHERE id=?", (preset_id,))
        c.commit()


def render(symbol: str, key: str = "cs", default_period: str = "3mo") -> None:
    """Render the full chart studio for `symbol`."""
    if not symbol:
        st.info("Pick a symbol to chart.")
        return

    # ---- Presets bar ----
    presets = _load_presets()
    pcol1, pcol2, pcol3 = st.columns([2.0, 2.0, 1.0])
    preset_choice = pcol1.selectbox(
        "Saved chart presets",
        ["(none)"] + [f"{p['name']} · {p['symbol']}" for p in presets],
        key=f"{key}_preset_pick",
    )
    if preset_choice != "(none)":
        idx = ["(none)"] + [f"{p['name']} · {p['symbol']}" for p in presets]
        sel = presets[idx.index(preset_choice) - 1]
        try:
            import json
            cfg = json.loads(sel["settings_json"])
            for k_, v in cfg.items():
                st.session_state[f"{key}_{k_}"] = v
        except Exception:
            pass
    new_preset_name = pcol2.text_input("Save current as", placeholder="e.g. ASTS earnings setup",
                                        label_visibility="visible", key=f"{key}_preset_name")
    save_clicked = pcol3.button("Save", key=f"{key}_save_preset")
    if save_clicked and new_preset_name:
        # collect current settings from session state
        keys_to_save = ["src", "period", "interval", "style", "pov",
                        "s20", "s50", "s200", "ema", "bb", "vol", "lower"]
        cfg = {k_: st.session_state.get(f"{key}_{k_}") for k_ in keys_to_save
               if f"{key}_{k_}" in st.session_state}
        _save_preset(new_preset_name, symbol, cfg)
        st.toast(f"Preset '{new_preset_name}' saved", icon="✓")

    # ---- Top control row 1: source / period / interval / style / POV ----
    c1, c2, c3, c4, c5 = st.columns([1.1, 1.0, 1.0, 1.4, 1.6])
    source = c1.selectbox("Source", ["yfinance", "TradingView"], key=f"{key}_src")

    if source == "TradingView":
        # Defer entirely to the TV widget — it has its own controls
        tv_html = f"""
        <div class="tradingview-widget-container" style="height:560px;">
          <div id="tv_widget_{key}"></div>
          <script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>
          <script type="text/javascript">
            new TradingView.widget({{
              "autosize": true,
              "symbol": "NASDAQ:{symbol}",
              "interval": "D",
              "timezone": "Etc/UTC",
              "theme": "dark",
              "style": "1",
              "locale": "en",
              "container_id": "tv_widget_{key}",
              "studies": ["MASimple@tv-basicstudies","RSI@tv-basicstudies"],
              "withdateranges": true,
              "details": true,
              "hotlist": true,
              "calendar": true,
              "allow_symbol_change": true
            }});
          </script>
        </div>
        """
        st.components.v1.html(tv_html, height=580, scrolling=False)
        st.caption(":bulb: TradingView's own chart — log into TradingView in this browser to bring "
                   "your saved indicators and drawings.")
        return

    period = c2.selectbox(
        "Period", list(PERIOD_INTERVALS.keys()),
        index=list(PERIOD_INTERVALS.keys()).index(default_period),
        key=f"{key}_period",
    )
    intervals = PERIOD_INTERVALS[period]
    default_iv = DEFAULT_INTERVAL[period]
    if default_iv not in intervals:
        default_iv = intervals[0]
    interval = c3.selectbox(
        "Interval", intervals, index=intervals.index(default_iv), key=f"{key}_interval",
    )
    style = c4.radio("Style", ["Candles", "OHLC", "Line", "Area"],
                     horizontal=True, label_visibility="collapsed", key=f"{key}_style")
    pov = c5.selectbox(
        "POV",
        ["Price", "+ Sentiment overlay", "+ News density", "+ Earnings markers", "Relative vs SPY"],
        key=f"{key}_pov",
    )

    # ---- Overlay row ----
    o = st.columns(7)
    show_sma20 = o[0].checkbox("SMA20", value=(period not in {"1d"}), key=f"{key}_s20")
    show_sma50 = o[1].checkbox("SMA50", value=(period not in {"1d", "5d"}), key=f"{key}_s50")
    show_sma200 = o[2].checkbox("SMA200", value=False, key=f"{key}_s200")
    show_ema = o[3].checkbox("EMA 12/26", value=False, key=f"{key}_ema")
    show_bb = o[4].checkbox("Bollinger", value=False, key=f"{key}_bb")
    show_vol = o[5].checkbox("Volume", value=True, key=f"{key}_vol")
    show_rsi_macd = o[6].selectbox("Lower panel", ["None", "RSI", "MACD"],
                                    index=0, label_visibility="collapsed", key=f"{key}_lower")

    # ---- Fetch ----
    with st.spinner(f"Fetching {symbol} {period}/{interval}..."):
        df = _fetch(symbol, period, interval)
    if df.empty:
        st.warning(f"No data returned for {symbol} {period}/{interval}. "
                   "Try a wider period or different interval.")
        return

    closes = df["Close"].values.astype(float)
    opens = df["Open"].values.astype(float)
    highs = df["High"].values.astype(float)
    lows = df["Low"].values.astype(float)
    vols = df["Volume"].values.astype(float)
    x = df["ts"]

    # ---- Relative-vs-SPY POV ----
    if pov == "Relative vs SPY":
        spy = _fetch("SPY", period, interval)
        if spy.empty:
            st.warning("Could not fetch SPY for relative comparison.")
            return
        merged = pd.merge(df[["ts", "Close"]], spy[["ts", "Close"]], on="ts", suffixes=("_t", "_spy"))
        if merged.empty:
            st.warning("No overlap between ticker and SPY for this period/interval.")
            return
        # Normalize each to start at 100
        t_norm = merged["Close_t"] / merged["Close_t"].iloc[0] * 100
        spy_norm = merged["Close_spy"] / merged["Close_spy"].iloc[0] * 100
        rel = t_norm - spy_norm  # positive = outperforming
        fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.62, 0.38],
                            vertical_spacing=0.06)
        fig.add_trace(go.Scatter(x=merged["ts"], y=t_norm, name=symbol,
                                  line=dict(color=ui_style.ACCENT, width=2.4)), row=1, col=1)
        fig.add_trace(go.Scatter(x=merged["ts"], y=spy_norm, name="SPY",
                                  line=dict(color=ui_style.NEUTRAL, width=1.6)), row=1, col=1)
        fig.add_trace(go.Bar(x=merged["ts"], y=rel, name=f"{symbol} − SPY",
                              marker_color=np.where(rel >= 0, ui_style.BULL, ui_style.BEAR)),
                      row=2, col=1)
        fig.update_yaxes(title="indexed (=100)", row=1, col=1)
        fig.update_yaxes(title="alpha vs SPY", row=2, col=1)
        ui_style.style_fig(fig, height=520)
        st.plotly_chart(fig, use_container_width=True)
        st.caption(":bulb: Top: each line normalized to 100 at period start. Bottom: "
                   "relative performance (positive = outperforming SPY).")
        return

    # ---- Build subplot stack: main + (vol) + (rsi or macd) ----
    rows = 1
    row_heights = [1.0]
    vol_row = rsi_row = macd_row = None
    if show_vol:
        rows += 1
        row_heights.append(0.18)
        vol_row = rows
    if show_rsi_macd == "RSI":
        rows += 1
        row_heights.append(0.22)
        rsi_row = rows
    elif show_rsi_macd == "MACD":
        rows += 1
        row_heights.append(0.26)
        macd_row = rows
    # Normalize heights
    s = sum(row_heights)
    row_heights = [r / s for r in row_heights]

    fig = make_subplots(rows=rows, cols=1, shared_xaxes=True,
                        row_heights=row_heights, vertical_spacing=0.04,
                        specs=[[{"secondary_y": True}]] + [[{}]] * (rows - 1))

    # Main price
    if style == "Candles":
        fig.add_trace(go.Candlestick(
            x=x, open=opens, high=highs, low=lows, close=closes,
            name=symbol, **ui_style.CANDLE_COLORS,
        ), row=1, col=1, secondary_y=False)
    elif style == "OHLC":
        fig.add_trace(go.Ohlc(
            x=x, open=opens, high=highs, low=lows, close=closes,
            name=symbol,
            increasing_line_color=ui_style.BULL, decreasing_line_color=ui_style.BEAR,
        ), row=1, col=1, secondary_y=False)
    elif style == "Line":
        fig.add_trace(go.Scatter(
            x=x, y=closes, mode="lines", name=symbol, line=ui_style.LINE_PRIMARY,
        ), row=1, col=1, secondary_y=False)
    else:  # Area
        fig.add_trace(go.Scatter(
            x=x, y=closes, mode="lines", name=symbol,
            line=ui_style.LINE_PRIMARY, fill="tozeroy",
            fillcolor="rgba(0,212,170,0.10)",
        ), row=1, col=1, secondary_y=False)

    # Overlays
    if show_sma20 and len(closes) >= 20:
        fig.add_trace(go.Scatter(x=x, y=_sma(closes, 20), mode="lines",
                                  name="SMA20", line=ui_style.LINE_MA20),
                      row=1, col=1, secondary_y=False)
    if show_sma50 and len(closes) >= 50:
        fig.add_trace(go.Scatter(x=x, y=_sma(closes, 50), mode="lines",
                                  name="SMA50", line=ui_style.LINE_MA50),
                      row=1, col=1, secondary_y=False)
    if show_sma200 and len(closes) >= 200:
        fig.add_trace(go.Scatter(x=x, y=_sma(closes, 200), mode="lines",
                                  name="SMA200", line=ui_style.LINE_MA200),
                      row=1, col=1, secondary_y=False)
    if show_ema:
        fig.add_trace(go.Scatter(x=x, y=_ema(closes, 12), mode="lines",
                                  name="EMA12", line=dict(color="#ffd166", width=1.2)),
                      row=1, col=1, secondary_y=False)
        fig.add_trace(go.Scatter(x=x, y=_ema(closes, 26), mode="lines",
                                  name="EMA26", line=dict(color="#06d6a0", width=1.2, dash="dot")),
                      row=1, col=1, secondary_y=False)
    if show_bb and len(closes) >= 20:
        mid, up, lo = _bbands(closes, 20, 2.0)
        fig.add_trace(go.Scatter(x=x, y=up, mode="lines", name="BB upper",
                                  line=dict(color="rgba(78,161,255,0.5)", width=1)),
                      row=1, col=1, secondary_y=False)
        fig.add_trace(go.Scatter(x=x, y=lo, mode="lines", name="BB lower",
                                  line=dict(color="rgba(78,161,255,0.5)", width=1),
                                  fill="tonexty", fillcolor="rgba(78,161,255,0.06)"),
                      row=1, col=1, secondary_y=False)

    # ---- POV overlays on main chart ----
    if pov == "+ Sentiment overlay":
        nd = _news_density(symbol, x)
        if nd is not None and len(nd) >= 3:
            # Daily-bucket rolling sentiment, plotted on secondary y-axis
            nd_daily = nd.set_index("ts").resample("D")["sentiment"].mean().rolling(3).mean().dropna()
            fig.add_trace(go.Scatter(
                x=nd_daily.index, y=nd_daily.values, mode="lines",
                name="news sentiment (3d MA)",
                line=dict(color="#ffb547", width=1.8, dash="dot"),
            ), row=1, col=1, secondary_y=True)
            fig.update_yaxes(title="sentiment", range=[-1, 1], row=1, col=1, secondary_y=True,
                              gridcolor="rgba(0,0,0,0)")

    elif pov == "+ News density":
        nd = _news_density(symbol, x)
        if nd is not None:
            counts = nd.set_index("ts").resample("D").size()
            counts = counts[counts > 0]
            for ts_pt, cnt in counts.items():
                fig.add_vline(x=ts_pt, line=dict(color=f"rgba(78,161,255,{min(0.15 + cnt * 0.07, 0.5)})",
                                                  width=max(1, min(cnt, 4))),
                              row=1, col=1)

    elif pov == "+ Earnings markers":
        for ed in _earnings_dates(symbol):
            try:
                ed_ts = pd.Timestamp(ed)
                fig.add_vline(x=ed_ts, line=dict(color=ui_style.WARN, width=1.5, dash="dash"),
                              row=1, col=1, annotation_text="ER", annotation_position="top")
            except Exception:
                continue

    # Volume panel
    if show_vol and vol_row:
        vol_colors = np.where(closes >= opens, ui_style.BULL, ui_style.BEAR)
        fig.add_trace(go.Bar(x=x, y=vols, name="volume", marker_color=vol_colors,
                              marker_line_width=0, opacity=0.6),
                      row=vol_row, col=1)
        fig.update_yaxes(title="vol", row=vol_row, col=1)

    # RSI panel
    if rsi_row:
        rsi = _rsi(closes, 14)
        fig.add_trace(go.Scatter(x=x, y=rsi, mode="lines", name="RSI(14)",
                                  line=dict(color=ui_style.ACCENT_2, width=1.5)),
                      row=rsi_row, col=1)
        # 70/30 reference lines
        for lvl, clr in [(70, ui_style.BEAR), (30, ui_style.BULL)]:
            fig.add_hline(y=lvl, line=dict(color=clr, width=1, dash="dot"),
                          row=rsi_row, col=1)
        fig.update_yaxes(title="RSI", range=[0, 100], row=rsi_row, col=1)

    # MACD panel
    if macd_row:
        line, signal, hist = _macd(closes)
        macd_colors = np.where(hist >= 0, ui_style.BULL, ui_style.BEAR)
        fig.add_trace(go.Bar(x=x, y=hist, name="MACD hist",
                              marker_color=macd_colors, marker_line_width=0, opacity=0.55),
                      row=macd_row, col=1)
        fig.add_trace(go.Scatter(x=x, y=line, mode="lines", name="MACD",
                                  line=dict(color=ui_style.ACCENT, width=1.5)),
                      row=macd_row, col=1)
        fig.add_trace(go.Scatter(x=x, y=signal, mode="lines", name="signal",
                                  line=dict(color=ui_style.WARN, width=1.2, dash="dot")),
                      row=macd_row, col=1)
        fig.update_yaxes(title="MACD", row=macd_row, col=1)

    fig.update_layout(showlegend=True, hovermode="x unified")
    ui_style.style_fig(fig, height=520 + (140 if show_vol else 0)
                                       + (160 if rsi_row or macd_row else 0))
    fig.update_layout(xaxis_rangeslider_visible=False)
    st.plotly_chart(fig, use_container_width=True)
