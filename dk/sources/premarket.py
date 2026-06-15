"""US pre-market gap scanner — keyless, via yfinance prepost intraday bars.

yfinance history(interval='5m', prepost=True) returns extended-hours bars
including the 4:00-9:30 ET pre-market window. For each symbol we take the latest
pre-market print and compare it to the prior regular-session close = the gap %.
No API key, works from the Railway IP (same path the regular price fetch uses).
Covers the watchlist plus the day's biggest movers so a surprise gapper off-list
still surfaces. Returns nothing outside the pre-market window (no pre-market
bars), which is the correct quiet behavior.

fetch_premarket / scan_gaps return a (data, health) pair so callers can tell a
genuinely quiet tape (failed=0, no gappers) from a Yahoo IP block (failed≈total)
— important for a pre-open decision feed with no Stooq-style intraday fallback.
"""
from __future__ import annotations
import random
import time as _time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import time
import yfinance as yf
from dk.util.session import ET, now_et

_PM_START = time(4, 0)
_RTH_OPEN = time(9, 30)
_RTH_CLOSE = time(16, 0)


def _gap_from_hist(hist) -> dict | None:
    """Compute the pre-market gap from a prepost intraday DataFrame, or None."""
    if hist is None or hist.empty:
        return None
    try:
        idx = hist.index.tz_convert(ET)  # localize to ET to classify sessions
    except Exception:
        return None
    closes = hist["Close"].tolist()
    vols = hist["Volume"].tolist() if "Volume" in hist.columns else [0.0] * len(closes)
    dates = [d.date() for d in idx]
    times = [d.time() for d in idx]
    # Anchor on the ACTUAL current ET date, not the last bar's date — otherwise
    # overnight/weekend (when the last bar is a prior session) we'd report a stale
    # historical gap as if it were live.
    today = now_et().date()

    # Latest pre-market print today (and pre-market cumulative volume).
    pm_close = None
    pm_vol = 0.0
    for cl, vol, d, t in zip(closes, vols, dates, times):
        if d == today and _PM_START <= t < _RTH_OPEN and cl == cl:  # cl==cl filters NaN
            pm_close = float(cl)
            pm_vol += float(vol) if vol == vol else 0.0
    if pm_close is None:
        return None  # no pre-market prints yet — quiet

    # Prior regular-session close: last bar on an earlier date STRICTLY before
    # 16:00 ET. Bars are labeled by open time, so the 15:55 bar is the last RTH
    # bar (its close = the official close); the 16:00 bar is the first after-hours
    # print, so the bound must be strict (< not <=).
    prev_close = None
    for cl, d, t in zip(closes, dates, times):
        if d < today and t < _RTH_CLOSE and cl == cl:
            prev_close = float(cl)
    if prev_close is None:  # fallback: any earlier-date bar
        for cl, d in zip(closes, dates):
            if d < today and cl == cl:
                prev_close = float(cl)
    if not prev_close:
        return None

    gap = (pm_close - prev_close) / prev_close * 100.0
    return {"premarket": round(pm_close, 4), "prev_close": round(prev_close, 4),
            "gap_pct": round(gap, 2), "premarket_vol": round(pm_vol)}


def _fetch_one(symbol: str):
    """(symbol, gap_or_None, ok) — ok=False means the fetch itself failed/empty
    (distinct from a successful fetch with no pre-market prints)."""
    # Small stagger so 5 workers don't all hit Yahoo on the same instant (the
    # datacenter-IP throttle pattern). period='7d' so the prior regular session is
    # in-frame even after a Monday holiday / long weekend. auto_adjust=False so
    # prev_close is the raw printed close (no ex-div/split adjustment skewing the
    # gap), matching prices_yfinance.py.
    _time.sleep(random.uniform(0, 0.4))
    try:
        h = yf.Ticker(symbol).history(period="7d", interval="5m",
                                      prepost=True, auto_adjust=False)
        ok = h is not None and not h.empty
        return symbol, _gap_from_hist(h), ok
    except Exception:
        return symbol, None, False


def fetch_premarket(symbols, max_workers: int = 5) -> tuple[dict, dict]:
    """Returns ({SYMBOL: gap_dict}, health). health={total, failed, degraded}.
    degraded=True when most symbols failed to fetch (likely a Yahoo IP block),
    so callers don't render an outage as a quiet tape."""
    symbols = list(dict.fromkeys(s.upper() for s in symbols if s))
    out: dict[str, dict] = {}
    failed = 0
    if not symbols:
        return out, {"total": 0, "failed": 0, "degraded": False}
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = [ex.submit(_fetch_one, s) for s in symbols]
        for fut in as_completed(futs):
            sym, g, ok = fut.result()  # _fetch_one never raises
            if not ok:
                failed += 1
            if g:
                out[sym] = g
    total = len(symbols)
    degraded = total > 0 and failed >= max(3, int(total * 0.8))
    return out, {"total": total, "failed": failed, "degraded": degraded}


def scan_gaps(watchlist_syms, movers_syms=None, watchlist_min_pct: float = 2.0,
              movers_min_pct: float = 4.0, max_movers: int = 30) -> tuple[list[dict], dict]:
    """(ranked gappers, health). Watchlist names use a lower threshold than the
    noisier off-list movers; each row flags on_watchlist."""
    watch = {s.upper() for s in watchlist_syms if s}
    movers = [s.upper() for s in (movers_syms or [])][:max_movers]
    universe = list(watch) + [m for m in movers if m not in watch]
    quotes, health = fetch_premarket(universe)
    gappers = []
    for sym, g in quotes.items():
        on_wl = sym in watch
        thr = watchlist_min_pct if on_wl else movers_min_pct
        if abs(g["gap_pct"]) >= thr:
            gappers.append({"symbol": sym, "on_watchlist": on_wl, **g})
    gappers.sort(key=lambda x: abs(x["gap_pct"]), reverse=True)
    return gappers, health
