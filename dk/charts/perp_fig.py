"""Perp candlestick figure builder — Streamlit-free, shared by the dashboard
(dk.ui.perp_chart) and the headless Telegram push (dk.analysis.perp_scanner).

build_figure() assembles a Plotly figure (candles + indicators + the measured
entry/stop/TP overlay). chart_png() renders that figure to PNG bytes via kaleido
for sending as a Telegram photo — returns None (not raise) if export is
unavailable, so the caller can fall back to a text alert.

Colors are inlined (a fixed dark palette) rather than imported from dk.ui.style,
which pulls in Streamlit.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from dk.sources import crypto_deriv
from dk.analysis import perp

# ---- palette (mirror of dk.ui.style, kept local to avoid the streamlit import) ----
ACCENT = "#00d4aa"
ACCENT_2 = "#4ea1ff"
BULL = "#00d4aa"
BEAR = "#ff5d5d"
NEUTRAL = "#7c8aa8"
WARN = "#ffb547"
MA50_COLOR = "#b66dff"
_BG = "#0e1117"
_TEXT = "#e6e9ef"
_GRID = "rgba(255,255,255,0.06)"
_BORDER = "#2a2e39"
CANDLE_COLORS = dict(
    increasing_line_color=BULL, increasing_fillcolor=BULL,
    decreasing_line_color=BEAR, decreasing_fillcolor=BEAR,
)

# Blofin bar -> (bar code, bars to pull). Tuned per timeframe for a clean window.
TIMEFRAMES = {
    "5m":  ("5m",  120),   # ~10h
    "15m": ("15m", 96),    # ~24h
    "1H":  ("1H",  120),   # ~5d
    "4H":  ("4H",  120),   # ~20d
    "1D":  ("1D",  120),   # ~120d
}
TIMEFRAME_KEYS = list(TIMEFRAMES.keys())


def norm_pair(pair: str) -> str:
    """Mirror perp.analyze normalization: bare base -> USDT perp, upper-cased."""
    p = (pair or "").strip().upper()
    if not p:
        return ""
    return p if "-" in p else f"{p}-USDT"


def fetch_df(inst_id: str, timeframe: str) -> pd.DataFrame:
    bar, limit = TIMEFRAMES.get(timeframe, ("1H", 120))
    rows = crypto_deriv.fetch_candles(inst_id, bar=bar, limit=limit)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)  # ts(ms), open, high, low, close, vol — oldest first
    df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    return df


# ---- indicators (numpy; no streamlit) ----
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


def draw_setup(fig, s: dict | None, side: str) -> None:
    """Draw entry / stop / TP ladder for one side as horizontal lines on row 1."""
    if not s or not s.get("entry"):
        return
    f = perp._fmt
    tag = "L" if side == "long" else "S"
    fig.add_hline(y=s["entry"], row=1, col=1,
                  line=dict(color=NEUTRAL, width=1.3, dash="dot"),
                  annotation_text=f"{tag} entry ${f(s['entry'])}",
                  annotation_position="right")
    if s.get("stop"):
        fig.add_hline(y=s["stop"], row=1, col=1,
                      line=dict(color=BEAR, width=1.4, dash="dash"),
                      annotation_text=f"{tag} stop ${f(s['stop'])} ({s.get('risk_pct')}%)",
                      annotation_position="right")
    for i, tp in enumerate(s.get("tps", []), 1):
        star = "*" if tp.get("basis") == "R-mult" else ""
        fig.add_hline(y=tp["level"], row=1, col=1,
                      line=dict(color=BULL, width=1.1,
                                dash="solid" if star == "" else "dot"),
                      annotation_text=f"{tag} TP{i} ${f(tp['level'])} ({tp['r']}R{star})",
                      annotation_position="right")


def _style(fig, height: int) -> None:
    fig.update_layout(
        height=height, paper_bgcolor=_BG, plot_bgcolor=_BG,
        font=dict(color=_TEXT, family="Inter, system-ui, sans-serif", size=12),
        xaxis=dict(gridcolor=_GRID, linecolor=_BORDER, tickcolor=_BORDER),
        yaxis=dict(gridcolor=_GRID, linecolor=_BORDER, tickcolor=_BORDER),
        legend=dict(bgcolor="rgba(0,0,0,0)", bordercolor=_BORDER, borderwidth=1),
        margin=dict(l=8, r=8, t=40, b=8),
        showlegend=True, hovermode="x unified",
        xaxis_rangeslider_visible=False,
    )


def build_figure(inst_id: str, df: pd.DataFrame, a: dict | None, *,
                 timeframe: str = "1H", overlay: str = "Both", lower: str = "RSI",
                 show_vol: bool = True, show_ma20: bool = True, show_ma50: bool = True,
                 show_ema: bool = False, show_bb: bool = False,
                 title: str | None = None):
    """Assemble the perp figure from a fetched df + analysis dict (both pure)."""
    closes = df["close"].values.astype(float)
    opens = df["open"].values.astype(float)
    highs = df["high"].values.astype(float)
    lows = df["low"].values.astype(float)
    vols = df["vol"].values.astype(float)
    x = df["ts"]

    rows, row_heights = 1, [1.0]
    vol_row = lower_row = None
    if show_vol:
        rows += 1; row_heights.append(0.18); vol_row = rows
    if lower in ("RSI", "MACD"):
        rows += 1; row_heights.append(0.24); lower_row = rows
    tot = sum(row_heights)
    row_heights = [r / tot for r in row_heights]
    fig = make_subplots(rows=rows, cols=1, shared_xaxes=True,
                        row_heights=row_heights, vertical_spacing=0.04)

    fig.add_trace(go.Candlestick(x=x, open=opens, high=highs, low=lows, close=closes,
                                 name=inst_id, **CANDLE_COLORS), row=1, col=1)
    if show_ma20 and len(closes) >= 20:
        fig.add_trace(go.Scatter(x=x, y=_sma(closes, 20), mode="lines", name="MA20",
                                 line=dict(color=ACCENT_2, width=1.4)), row=1, col=1)
    if show_ma50 and len(closes) >= 50:
        fig.add_trace(go.Scatter(x=x, y=_sma(closes, 50), mode="lines", name="MA50",
                                 line=dict(color=MA50_COLOR, width=1.4)), row=1, col=1)
    if show_ema:
        fig.add_trace(go.Scatter(x=x, y=_ema(closes, 12), mode="lines", name="EMA12",
                                 line=dict(color="#ffd166", width=1.2)), row=1, col=1)
        fig.add_trace(go.Scatter(x=x, y=_ema(closes, 26), mode="lines", name="EMA26",
                                 line=dict(color="#06d6a0", width=1.2, dash="dot")), row=1, col=1)
    if show_bb and len(closes) >= 20:
        mid, up, lo = _bbands(closes, 20, 2.0)
        fig.add_trace(go.Scatter(x=x, y=up, mode="lines", name="BB upper",
                                 line=dict(color="rgba(78,161,255,0.5)", width=1)), row=1, col=1)
        fig.add_trace(go.Scatter(x=x, y=lo, mode="lines", name="BB lower",
                                 line=dict(color="rgba(78,161,255,0.5)", width=1),
                                 fill="tonexty", fillcolor="rgba(78,161,255,0.06)"), row=1, col=1)

    if a and overlay != "None":
        if overlay in ("Long", "Both"):
            draw_setup(fig, a.get("long"), "long")
        if overlay in ("Short", "Both"):
            draw_setup(fig, a.get("short"), "short")

    if vol_row:
        vc = np.where(closes >= opens, BULL, BEAR)
        fig.add_trace(go.Bar(x=x, y=vols, name="vol", marker_color=vc,
                             marker_line_width=0, opacity=0.6), row=vol_row, col=1)
        fig.update_yaxes(title="vol", row=vol_row, col=1)

    if lower_row and lower == "RSI":
        rsi = _rsi(closes, 14)
        fig.add_trace(go.Scatter(x=x, y=rsi, mode="lines", name="RSI(14)",
                                 line=dict(color=ACCENT_2, width=1.5)), row=lower_row, col=1)
        for lvl, clr in [(70, BEAR), (30, BULL)]:
            fig.add_hline(y=lvl, line=dict(color=clr, width=1, dash="dot"), row=lower_row, col=1)
        fig.update_yaxes(title="RSI", range=[0, 100], row=lower_row, col=1)
    elif lower_row and lower == "MACD":
        line, signal, hist = _macd(closes)
        mc = np.where(hist >= 0, BULL, BEAR)
        fig.add_trace(go.Bar(x=x, y=hist, name="MACD hist", marker_color=mc,
                             marker_line_width=0, opacity=0.55), row=lower_row, col=1)
        fig.add_trace(go.Scatter(x=x, y=line, mode="lines", name="MACD",
                                 line=dict(color=ACCENT, width=1.5)), row=lower_row, col=1)
        fig.add_trace(go.Scatter(x=x, y=signal, mode="lines", name="signal",
                                 line=dict(color=WARN, width=1.2, dash="dot")), row=lower_row, col=1)
        fig.update_yaxes(title="MACD", row=lower_row, col=1)

    if title:
        fig.update_layout(title=dict(text=title, x=0.01, xanchor="left",
                                     font=dict(size=15, color=_TEXT)))
    _style(fig, height=560 + (120 if show_vol else 0) + (150 if lower_row else 0))
    return fig


def chart_png(pair: str, *, timeframe: str = "1H", overlay: str = "Both",
              lower: str = "RSI", width: int = 1180, height: int = 760,
              scale: int = 2, title: str | None = None) -> bytes | None:
    """Render the perp chart to PNG bytes for a Telegram photo. Returns None on
    any failure (no candles, or kaleido/Chrome unavailable) so the caller can
    fall back to a text alert."""
    inst = norm_pair(pair)
    if not inst:
        return None
    df = fetch_df(inst, timeframe)
    if df.empty:
        return None
    try:
        a = perp.analyze(inst)
    except Exception as e:
        print(f"[perp_fig] analyze({inst}) failed: {e}")
        a = None
    if title is None:
        title = f"{inst} · {timeframe}" + (f" · {overlay} setup" if a and overlay != "None" else "")
    fig = build_figure(inst, df, a, timeframe=timeframe, overlay=overlay, lower=lower,
                       title=title)
    try:
        return fig.to_image(format="png", width=width, height=height, scale=scale)
    except Exception as e:
        print(f"[perp_fig] PNG export failed (kaleido/Chrome?): {e}")
        return None
