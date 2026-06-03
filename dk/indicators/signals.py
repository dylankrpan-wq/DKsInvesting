"""Technical signal detector — turns price history into named, actionable events.

Detects FRESH technical events (today vs yesterday) so you know not just the
state but the *transition* — e.g. "MACD just crossed bullish", "RSI just exited
oversold", "golden cross today", "broke to a new 52-week high on 3x volume".

Each signal: {code, label, lean ('bull'|'bear'|'neutral'), strength (1-3), detail}.
Reads from the prices table; works for any symbol that has >= ~30 daily bars.
"""
from __future__ import annotations
import sqlite3
import numpy as np
from dk.config import DB_PATH


def _series(symbol: str, limit: int = 260):
    with sqlite3.connect(DB_PATH) as c:
        rows = c.execute(
            "SELECT ts, high, low, close, volume FROM prices WHERE symbol=? ORDER BY ts ASC",
            (symbol,),
        ).fetchall()
    rows = rows[-limit:]
    closes = np.array([r[3] for r in rows if r[3] is not None], dtype=float)
    highs = np.array([r[1] for r in rows if r[1] is not None], dtype=float)
    lows = np.array([r[2] for r in rows if r[2] is not None], dtype=float)
    vols = np.array([r[4] for r in rows if r[4] is not None], dtype=float)
    return closes, highs, lows, vols


def _sma(x, n):
    if len(x) < n:
        return np.full(len(x), np.nan)
    c = np.cumsum(np.insert(x, 0, 0.0))
    return np.concatenate([np.full(n - 1, np.nan), (c[n:] - c[:-n]) / n])


def _ema(x, n):
    if len(x) == 0:
        return x
    a = 2.0 / (n + 1)
    out = np.empty(len(x))
    out[0] = x[0]
    for i in range(1, len(x)):
        out[i] = a * x[i] + (1 - a) * out[i - 1]
    return out


def _rsi_series(x, n=14):
    if len(x) < n + 1:
        return np.full(len(x), np.nan)
    d = np.diff(x, prepend=x[0])
    gain = np.where(d > 0, d, 0.0)
    loss = np.where(d < 0, -d, 0.0)
    ag = np.full(len(x), np.nan)
    al = np.full(len(x), np.nan)
    ag[n] = gain[1:n + 1].mean()
    al[n] = loss[1:n + 1].mean()
    for i in range(n + 1, len(x)):
        ag[i] = (ag[i - 1] * (n - 1) + gain[i]) / n
        al[i] = (al[i - 1] * (n - 1) + loss[i]) / n
    rs = np.where(al == 0, np.inf, ag / al)
    return 100.0 - 100.0 / (1.0 + rs)


def detect(symbol: str) -> list[dict]:
    closes, highs, lows, vols = _series(symbol)
    sigs: list[dict] = []
    if len(closes) < 30:
        return sigs

    last = closes[-1]
    prev = closes[-2]

    # --- RSI ---
    rsi = _rsi_series(closes, 14)
    r0, r1 = rsi[-1], rsi[-2]
    if not np.isnan(r0):
        if r1 >= 30 and r0 < 30:
            sigs.append({"code": "RSI_OVERSOLD", "label": "RSI dropped into oversold (<30)",
                         "lean": "bull", "strength": 2, "detail": f"RSI {r0:.0f} — washout / bounce setup"})
        elif r1 <= 30 and r0 > 30:
            sigs.append({"code": "RSI_EXIT_OVERSOLD", "label": "RSI reclaimed 30 (exiting oversold)",
                         "lean": "bull", "strength": 2, "detail": f"RSI {r0:.0f} — reversal momentum"})
        elif r1 <= 70 and r0 > 70:
            sigs.append({"code": "RSI_OVERBOUGHT", "label": "RSI pushed into overbought (>70)",
                         "lean": "bear", "strength": 1, "detail": f"RSI {r0:.0f} — extended, chase risk"})
        elif r1 < 50 and r0 >= 50:
            sigs.append({"code": "RSI_CROSS_50", "label": "RSI crossed above 50",
                         "lean": "bull", "strength": 1, "detail": f"RSI {r0:.0f} — momentum turning up"})

    # --- MACD ---
    if len(closes) >= 35:
        macd = _ema(closes, 12) - _ema(closes, 26)
        signal = _ema(macd, 9)
        h0, h1 = macd[-1] - signal[-1], macd[-2] - signal[-2]
        if h1 <= 0 and h0 > 0:
            sigs.append({"code": "MACD_BULL_CROSS", "label": "MACD bullish crossover (today)",
                         "lean": "bull", "strength": 2, "detail": "MACD line crossed above signal"})
        elif h1 >= 0 and h0 < 0:
            sigs.append({"code": "MACD_BEAR_CROSS", "label": "MACD bearish crossover (today)",
                         "lean": "bear", "strength": 2, "detail": "MACD line crossed below signal"})

    # --- Moving-average crosses ---
    if len(closes) >= 200:
        s50, s200 = _sma(closes, 50), _sma(closes, 200)
        if not np.isnan(s50[-2]) and not np.isnan(s200[-2]):
            if s50[-2] <= s200[-2] and s50[-1] > s200[-1]:
                sigs.append({"code": "GOLDEN_CROSS", "label": "Golden cross (50d over 200d)",
                             "lean": "bull", "strength": 3, "detail": "Major long-term bullish signal"})
            elif s50[-2] >= s200[-2] and s50[-1] < s200[-1]:
                sigs.append({"code": "DEATH_CROSS", "label": "Death cross (50d under 200d)",
                             "lean": "bear", "strength": 3, "detail": "Major long-term bearish signal"})
    if len(closes) >= 50:
        s50 = _sma(closes, 50)
        if not np.isnan(s50[-2]):
            if prev <= s50[-2] and last > s50[-1]:
                sigs.append({"code": "SMA50_RECLAIM", "label": "Reclaimed the 50-day MA",
                             "lean": "bull", "strength": 1, "detail": "Price crossed back above 50d SMA"})
            elif prev >= s50[-2] and last < s50[-1]:
                sigs.append({"code": "SMA50_LOSS", "label": "Lost the 50-day MA",
                             "lean": "bear", "strength": 1, "detail": "Price fell below 50d SMA"})

    # --- Bollinger breakouts ---
    if len(closes) >= 20:
        window = closes[-20:]
        mid = window.mean()
        sd = window.std(ddof=0)
        upper, lower = mid + 2 * sd, mid - 2 * sd
        prev_window = closes[-21:-1]
        pmid, psd = prev_window.mean(), prev_window.std(ddof=0)
        pupper, plower = pmid + 2 * psd, pmid - 2 * psd
        if prev <= pupper and last > upper:
            sigs.append({"code": "BB_BREAKOUT_UP", "label": "Broke above upper Bollinger band",
                         "lean": "bull", "strength": 2, "detail": "Volatility expansion to the upside"})
        elif prev >= plower and last < lower:
            sigs.append({"code": "BB_BREAKDOWN", "label": "Broke below lower Bollinger band",
                         "lean": "bear", "strength": 2, "detail": "Volatility expansion to the downside"})

    # --- 52-week breaks ---
    look = closes[-min(252, len(closes)):]
    hi52, lo52 = look.max(), look.min()
    if last >= hi52 and last > prev:
        sigs.append({"code": "NEW_52W_HIGH", "label": "New 52-week high",
                     "lean": "bull", "strength": 2, "detail": f"Breakout above ${hi52:,.2f}"})
    elif last <= lo52 and last < prev:
        sigs.append({"code": "NEW_52W_LOW", "label": "New 52-week low",
                     "lean": "bear", "strength": 2, "detail": f"Breakdown below ${lo52:,.2f}"})

    # --- Volume surge (confirmation) ---
    if len(vols) >= 21 and vols[-1] > 0:
        avg = vols[-21:-1].mean()
        if avg > 0 and vols[-1] >= 2 * avg:
            sigs.append({"code": "VOLUME_SURGE", "label": f"Volume {vols[-1]/avg:.1f}x average",
                         "lean": "neutral", "strength": 2, "detail": "Heavy participation — confirms the move"})

    # --- Trend stack (state, not transition) ---
    if len(closes) >= 200:
        s20, s50, s200 = _sma(closes, 20)[-1], _sma(closes, 50)[-1], _sma(closes, 200)[-1]
        if not any(np.isnan(v) for v in (s20, s50, s200)):
            if last > s20 > s50 > s200:
                sigs.append({"code": "STRONG_UPTREND", "label": "Stacked uptrend (price>20>50>200)",
                             "lean": "bull", "strength": 1, "detail": "All MAs aligned bullishly"})
            elif last < s20 < s50 < s200:
                sigs.append({"code": "STRONG_DOWNTREND", "label": "Stacked downtrend (price<20<50<200)",
                             "lean": "bear", "strength": 1, "detail": "All MAs aligned bearishly"})

    return sigs


def summarize(symbol: str) -> dict:
    """Return {signals, bull, bear, net_lean} for quick scoring."""
    sigs = detect(symbol)
    bull = sum(s["strength"] for s in sigs if s["lean"] == "bull")
    bear = sum(s["strength"] for s in sigs if s["lean"] == "bear")
    net = "bull" if bull > bear else ("bear" if bear > bull else "neutral")
    return {"signals": sigs, "bull": bull, "bear": bear, "net_lean": net}
