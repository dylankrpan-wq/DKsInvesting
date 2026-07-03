"""Lightweight signal backtester.

For a ticker + technical signal, find every past occurrence in the price history
and measure what happened next: did price reach +target% before -stop% within
the forward window? Returns a historical win-rate so a "setup forming" heads-up
comes with 'this setup has hit N% of the time on this name' context.

Fast + dependency-free (numpy on the stored close series).
"""
from __future__ import annotations
import sqlite3
import numpy as np
from dk.config import DB_PATH
from dk.indicators import signals as _sg

# Which codes we can backtest (must have a vectorizable fire condition below).
SUPPORTED = {
    "RSI_OVERSOLD", "RSI_EXIT_OVERSOLD", "MACD_BULL_CROSS", "SMA50_RECLAIM",
    "BB_BREAKOUT_UP", "NEW_52W_HIGH", "GOLDEN_CROSS",
}


def _closes(symbol: str, limit: int = 700) -> np.ndarray:
    with sqlite3.connect(DB_PATH) as c:
        rows = c.execute(
            "SELECT close FROM prices WHERE symbol=? ORDER BY ts ASC", (symbol,)
        ).fetchall()
    return np.array([r[0] for r in rows[-limit:] if r[0] is not None], dtype=float)


def _fire_indices(closes: np.ndarray, code: str) -> list[int]:
    n = len(closes)
    out: list[int] = []
    if code in ("RSI_OVERSOLD", "RSI_EXIT_OVERSOLD"):
        rsi = _sg._rsi_series(closes, 14)
        for i in range(1, n):
            if np.isnan(rsi[i]) or np.isnan(rsi[i - 1]):
                continue
            if code == "RSI_OVERSOLD" and rsi[i - 1] >= 30 and rsi[i] < 30:
                out.append(i)
            elif code == "RSI_EXIT_OVERSOLD" and rsi[i - 1] <= 30 and rsi[i] > 30:
                out.append(i)
    elif code == "MACD_BULL_CROSS":
        h = (_sg._ema(closes, 12) - _sg._ema(closes, 26))
        sig = _sg._ema(h, 9)
        d = h - sig
        for i in range(1, n):
            if d[i - 1] <= 0 and d[i] > 0:
                out.append(i)
    elif code == "SMA50_RECLAIM":
        s50 = _sg._sma(closes, 50)
        for i in range(1, n):
            if np.isnan(s50[i - 1]):
                continue
            if closes[i - 1] <= s50[i - 1] and closes[i] > s50[i]:
                out.append(i)
    elif code == "BB_BREAKOUT_UP":
        for i in range(21, n):
            w = closes[i - 20:i]
            up = w.mean() + 2 * w.std(ddof=0)
            pw = closes[i - 21:i - 1]
            pup = pw.mean() + 2 * pw.std(ddof=0)
            if closes[i - 1] <= pup and closes[i] > up:
                out.append(i)
    elif code == "NEW_52W_HIGH":
        for i in range(1, n):
            look = closes[max(0, i - 252):i + 1]
            if closes[i] >= look.max() and closes[i] > closes[i - 1]:
                out.append(i)
    elif code == "GOLDEN_CROSS":
        s50, s200 = _sg._sma(closes, 50), _sg._sma(closes, 200)
        for i in range(1, n):
            if np.isnan(s50[i - 1]) or np.isnan(s200[i - 1]):
                continue
            if s50[i - 1] <= s200[i - 1] and s50[i] > s200[i]:
                out.append(i)
    return out


def signal_hit_rate(symbol: str, code: str, forward_days: int = 10,
                    target_pct: float = 6.0, stop_pct: float = 5.0,
                    lookback: int = 700) -> dict | None:
    """Historical outcome of `code` on `symbol`. Returns None if not enough data
    or too few occurrences to be meaningful."""
    if code not in SUPPORTED:
        return None
    closes = _closes(symbol, lookback)
    if len(closes) < 120:
        return None
    idxs = [i for i in _fire_indices(closes, code) if i + forward_days < len(closes)]
    if len(idxs) < 4:            # need a few samples to mean anything
        return None
    wins, rets, max_gains = 0, [], []
    for i in idxs:
        entry = closes[i]
        fwd = closes[i + 1:i + 1 + forward_days]
        if len(fwd) == 0 or entry <= 0:
            continue
        max_gains.append((fwd.max() - entry) / entry * 100)
        rets.append((fwd[-1] - entry) / entry * 100)
        hit = False
        for p in fwd:
            chg = (p - entry) / entry * 100
            if chg >= target_pct:
                hit = True
                break
            if chg <= -stop_pct:
                break
        wins += 1 if hit else 0
    n = len(rets)
    if n < 4:
        return None
    return {
        "code": code, "n": n,
        "win_rate": round(wins / n * 100),
        "avg_return": round(sum(rets) / n, 1),
        "avg_max_gain": round(sum(max_gains) / n, 1),
        "target_pct": target_pct, "forward_days": forward_days,
    }


def best_backtest(symbol: str, codes: list[str], **kw) -> dict | None:
    """Backtest each supported code and return the one with the best win-rate
    (min 4 samples). Useful to annotate a fresh setup with its track record."""
    results = []
    for code in codes:
        if code not in SUPPORTED:
            continue
        r = signal_hit_rate(symbol, code, **kw)
        if r:
            results.append(r)
    if not results:
        return None
    results.sort(key=lambda x: (x["win_rate"], x["n"]), reverse=True)
    return results[0]
