"""Technical indicators on stored OHLCV. Pure numpy — no TA-Lib install pain.

Returns latest scalar values plus short series for charts. All readers tolerate
short price history gracefully (return None when not enough bars).
"""
from __future__ import annotations
import sqlite3
from dataclasses import dataclass, asdict
import numpy as np
from dk.config import DB_PATH


def _sma(x: np.ndarray, n: int) -> np.ndarray:
    if len(x) < n:
        return np.full_like(x, np.nan, dtype=float)
    c = np.cumsum(np.insert(x.astype(float), 0, 0.0))
    out = (c[n:] - c[:-n]) / n
    return np.concatenate([np.full(n - 1, np.nan), out])


def _ema(x: np.ndarray, n: int) -> np.ndarray:
    if len(x) == 0:
        return x
    alpha = 2.0 / (n + 1)
    out = np.empty_like(x, dtype=float)
    out[0] = x[0]
    for i in range(1, len(x)):
        out[i] = alpha * x[i] + (1 - alpha) * out[i - 1]
    return out


def _rsi(x: np.ndarray, n: int = 14) -> float | None:
    if len(x) < n + 1:
        return None
    deltas = np.diff(x.astype(float))
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    avg_gain = gains[:n].mean()
    avg_loss = losses[:n].mean()
    for i in range(n, len(deltas)):
        avg_gain = (avg_gain * (n - 1) + gains[i]) / n
        avg_loss = (avg_loss * (n - 1) + losses[i]) / n
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return float(100.0 - (100.0 / (1.0 + rs)))


def _macd(x: np.ndarray, fast: int = 12, slow: int = 26, sig: int = 9):
    if len(x) < slow + sig:
        return None, None, None
    macd_line = _ema(x, fast) - _ema(x, slow)
    signal = _ema(macd_line, sig)
    hist = macd_line - signal
    return float(macd_line[-1]), float(signal[-1]), float(hist[-1])


def _bbands(x: np.ndarray, n: int = 20, k: float = 2.0):
    if len(x) < n:
        return None, None, None, None
    window = x[-n:]
    mean = float(window.mean())
    sd = float(window.std(ddof=0))
    upper, lower = mean + k * sd, mean - k * sd
    pos = (float(x[-1]) - lower) / (upper - lower) if upper > lower else 0.5
    return mean, upper, lower, pos  # pos in [0,1] roughly


def _atr(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, n: int = 14) -> float | None:
    if len(closes) < n + 1:
        return None
    prev_close = closes[:-1]
    tr = np.maximum.reduce([
        highs[1:] - lows[1:],
        np.abs(highs[1:] - prev_close),
        np.abs(lows[1:] - prev_close),
    ])
    return float(np.mean(tr[-n:]))


@dataclass
class TASnapshot:
    symbol: str
    last_close: float | None = None
    sma20: float | None = None
    sma50: float | None = None
    sma200: float | None = None
    ema12: float | None = None
    ema26: float | None = None
    rsi14: float | None = None
    macd: float | None = None
    macd_signal: float | None = None
    macd_hist: float | None = None
    bb_mid: float | None = None
    bb_upper: float | None = None
    bb_lower: float | None = None
    bb_pos: float | None = None
    atr14: float | None = None
    high_52w: float | None = None
    low_52w: float | None = None
    pct_off_52w_high: float | None = None
    pct_above_52w_low: float | None = None
    vol_ratio_20d: float | None = None  # latest vol / 20d avg
    trend: str = "?"  # "up" | "down" | "sideways"
    setup_notes: list[str] = None

    def to_dict(self):
        d = asdict(self)
        d["setup_notes"] = self.setup_notes or []
        return d


def compute(symbol: str) -> TASnapshot:
    snap = TASnapshot(symbol=symbol, setup_notes=[])
    with sqlite3.connect(DB_PATH) as c:
        rows = c.execute(
            "SELECT ts, open, high, low, close, volume FROM prices WHERE symbol=? ORDER BY ts ASC",
            (symbol,),
        ).fetchall()
    if not rows or len(rows) < 5:
        return snap

    highs = np.array([r[2] for r in rows if r[2] is not None], dtype=float)
    lows = np.array([r[3] for r in rows if r[3] is not None], dtype=float)
    closes = np.array([r[4] for r in rows if r[4] is not None], dtype=float)
    vols = np.array([r[5] for r in rows if r[5] is not None], dtype=float)
    if len(closes) < 5:
        return snap

    snap.last_close = float(closes[-1])
    snap.sma20 = float(_sma(closes, 20)[-1]) if len(closes) >= 20 else None
    snap.sma50 = float(_sma(closes, 50)[-1]) if len(closes) >= 50 else None
    snap.sma200 = float(_sma(closes, 200)[-1]) if len(closes) >= 200 else None
    snap.ema12 = float(_ema(closes, 12)[-1])
    snap.ema26 = float(_ema(closes, 26)[-1])
    snap.rsi14 = _rsi(closes, 14)
    snap.macd, snap.macd_signal, snap.macd_hist = _macd(closes)
    snap.bb_mid, snap.bb_upper, snap.bb_lower, snap.bb_pos = _bbands(closes)
    snap.atr14 = _atr(highs, lows, closes, 14)

    last = float(closes[-1])
    snap.high_52w = float(closes[-min(252, len(closes)):].max())
    snap.low_52w = float(closes[-min(252, len(closes)):].min())
    if snap.high_52w:
        snap.pct_off_52w_high = (last - snap.high_52w) / snap.high_52w * 100
    if snap.low_52w:
        snap.pct_above_52w_low = (last - snap.low_52w) / snap.low_52w * 100

    if len(vols) >= 21:
        avg_v = float(vols[-21:-1].mean())
        if avg_v > 0:
            snap.vol_ratio_20d = float(vols[-1]) / avg_v

    # Trend classification
    if snap.sma20 and snap.sma50:
        if last > snap.sma20 > snap.sma50:
            snap.trend = "up"
        elif last < snap.sma20 < snap.sma50:
            snap.trend = "down"
        else:
            snap.trend = "sideways"
    else:
        snap.trend = "up" if last > closes[0] else "down"

    notes: list[str] = []
    if snap.rsi14 is not None:
        if snap.rsi14 >= 70:
            notes.append(f"RSI {snap.rsi14:.1f} — overbought")
        elif snap.rsi14 <= 30:
            notes.append(f"RSI {snap.rsi14:.1f} — oversold")
    if snap.macd_hist is not None:
        if snap.macd_hist > 0 and snap.macd is not None and snap.macd_signal is not None:
            if snap.macd > snap.macd_signal:
                notes.append("MACD bullish (line above signal, positive hist)")
        elif snap.macd_hist < 0:
            notes.append("MACD bearish (line below signal)")
    if snap.bb_pos is not None:
        if snap.bb_pos >= 0.95:
            notes.append("At/above upper Bollinger band — extended")
        elif snap.bb_pos <= 0.05:
            notes.append("At/below lower Bollinger band — stretched lower")
    if snap.pct_off_52w_high is not None and snap.pct_off_52w_high >= -2.0:
        notes.append("Within 2% of 52-week high")
    if snap.pct_above_52w_low is not None and snap.pct_above_52w_low <= 5.0:
        notes.append("Within 5% of 52-week low")
    if snap.vol_ratio_20d is not None and snap.vol_ratio_20d >= 2.0:
        notes.append(f"Volume {snap.vol_ratio_20d:.1f}x 20d avg")
    if snap.sma20 and snap.sma50 and snap.sma20 > snap.sma50:
        notes.append("20d SMA above 50d SMA (bullish stack)")
    elif snap.sma20 and snap.sma50 and snap.sma20 < snap.sma50:
        notes.append("20d SMA below 50d SMA (bearish stack)")
    snap.setup_notes = notes
    return snap
