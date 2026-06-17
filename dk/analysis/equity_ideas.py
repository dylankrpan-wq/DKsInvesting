"""Multi-horizon equity idea engine — short-term, swing, and long-term LONG
opportunities across a broad, liquid, cross-sector universe, each tagged by the
horizon its setup actually supports, with the logic that backs it and a
$100-minimum position size.

Two-stage like the perp scanner, to stay cheap:
  1. gather a cheap universe (market-wide movers + watchlist + discovered names),
     rank by a momentum/liquidity composite, keep a shortlist.
  2. deep technical analysis on the shortlist (reusing dk.indicators.ta +
     signals on stored daily bars) + relative strength vs SPY → classify horizon,
     build entry/stop/targets, collect the reasons, size at >= $100.

Keyless: price/volume technicals + relative strength + catalyst flags. No
fundamentals (that's a later, data-keyed upgrade), so long-term ideas are framed
on durable trend + relative-strength leadership, not valuation. Discovery, not
instructions — every idea carries its reasons and an invalidation (the stop).
"""
from __future__ import annotations
import sqlite3
from dk.config import DB_PATH, load_watchlist
from dk.sources import market_movers, prices_yfinance
from dk.indicators import ta, signals

MIN_TRADE_USD = 100.0      # the user's floor: never size a scenario under $100 notional
BENCH = "SPY"              # relative-strength benchmark
_RS_WINDOWS = (20, 60, 120)  # ~1m / 3m / 6m trading days


def _equity_watchlist() -> list[str]:
    wl = load_watchlist()
    out = []
    for grp in ("equities", "etfs"):
        for it in (wl.get(grp) or []):
            s = it.get("symbol") if isinstance(it, dict) else it
            if s:
                out.append(s.upper())
    return out


def _cap_class(mcap) -> str:
    if not mcap:
        return "?"
    if mcap < 2e9:
        return "small"
    if mcap < 1e10:
        return "mid"
    return "large"


def _closes(symbol: str) -> list[float]:
    with sqlite3.connect(DB_PATH) as c:
        rows = c.execute(
            "SELECT close FROM prices WHERE symbol=? AND close IS NOT NULL ORDER BY ts ASC",
            (symbol,)).fetchall()
    return [float(r[0]) for r in rows]


def _ret_pct(closes: list[float], n: int) -> float | None:
    if len(closes) <= n or closes[-1 - n] == 0:
        return None
    return (closes[-1] - closes[-1 - n]) / closes[-1 - n] * 100.0


def _ensure_history(symbol: str, period: str = "1y") -> None:
    """Make sure the prices table has enough daily history for the 200-day MA."""
    if len(_closes(symbol)) >= 200:
        return  # already deep enough this session
    try:
        prices_yfinance.fetch_prices(symbol, period=period, interval="1d")
    except Exception as e:
        print(f"[equity_ideas] history fetch {symbol}: {e}")


def _bench_returns() -> dict:
    _ensure_history(BENCH)
    closes = _closes(BENCH)
    return {n: _ret_pct(closes, n) for n in _RS_WINDOWS}


def gather_universe() -> dict:
    """Cheap cross-sector universe: market-wide movers + watchlist + discovered.
    {SYMBOL: {price, chg_pct, volume, market_cap, src}}."""
    uni: dict[str, dict] = {}
    try:
        for m in market_movers.fetch_movers():
            s = (m.get("symbol") or "").upper()
            if s:
                uni.setdefault(s, {"price": m.get("price"), "chg_pct": m.get("change_pct"),
                                   "volume": m.get("volume"), "market_cap": m.get("market_cap"),
                                   "src": "mover"})
    except Exception as e:
        print(f"[equity_ideas] movers: {e}")
    for s in _equity_watchlist():
        uni.setdefault(s, {"price": None, "chg_pct": None, "volume": None,
                           "market_cap": None, "src": "watchlist"})
    try:  # discovered market-scan names
        with sqlite3.connect(DB_PATH) as c:
            for r in c.execute(
                """SELECT symbol, last_price FROM candidates
                   WHERE discovered_via='market_scan'
                     AND last_seen >= datetime('now','-2 days')"""):
                s = (r[0] or "").upper()
                if s:
                    uni.setdefault(s, {"price": r[1], "chg_pct": None, "volume": None,
                                       "market_cap": None, "src": "discovered"})
    except Exception:
        pass
    return uni


def _shortlist(uni: dict, max_deep: int) -> list[str]:
    """Always analyze the watchlist; fill the rest with the most active/volatile
    movers (a cheap proxy for 'something is happening here')."""
    watch = [s for s, d in uni.items() if d.get("src") == "watchlist"]
    movers = [(s, d) for s, d in uni.items() if d.get("src") != "watchlist"]

    def _score(d):
        chg = abs(d.get("chg_pct") or 0)
        vol = d.get("volume") or 0
        return chg * 2 + (vol / 1e7)  # weight momentum, nudge by liquidity

    movers.sort(key=lambda kv: _score(kv[1]), reverse=True)
    ordered = watch + [s for s, _ in movers]
    seen, out = set(), []
    for s in ordered:
        if s not in seen:
            seen.add(s)
            out.append(s)
        if len(out) >= max_deep:
            break
    return out


def _build_idea(sym: str, snap, sig: dict, rs: dict, cheap: dict | None) -> dict | None:
    """Classify horizon + construct the long idea, or None if no clean setup."""
    price = snap.last_close
    if not price or price <= 0:
        return None
    atr = snap.atr14 or price * 0.03
    sigs = sig["signals"]
    codes = {s["code"] for s in sigs}
    above20 = bool(snap.sma20 and price > snap.sma20)
    above50 = bool(snap.sma50 and price > snap.sma50)
    above200 = bool(snap.sma200 and price > snap.sma200)
    stacked = bool(snap.sma20 and snap.sma50 and snap.sma200
                   and price > snap.sma20 > snap.sma50 > snap.sma200)
    ma50_gt_200 = bool(snap.sma50 and snap.sma200 and snap.sma50 > snap.sma200)
    rs60, rs120 = rs.get(60), rs.get(120)
    chg = abs((cheap or {}).get("chg_pct") or 0)

    # Long-bias only (this is an "investment ideas" engine). Bearish names skipped.
    bullish = sig["net_lean"] == "bull" or snap.trend == "up" or above50
    if not bullish:
        return None

    reasons: list[str] = []
    # Horizon by durability: durable trend -> long; fresh trend trigger -> swing;
    # near-term catalyst -> short.
    if above200 and ma50_gt_200 and stacked and (rs120 is None or rs120 >= 0):
        horizon = "long_term"
        reasons.append("durable stacked uptrend above a rising 200-day MA")
        if rs120 and rs120 > 0:
            reasons.append(f"+{rs120:.0f}% vs SPY over ~6mo (relative-strength leader)")
    elif above50 and ({"MACD_BULL_CROSS", "SMA50_RECLAIM", "BB_BREAKOUT_UP",
                       "NEW_52W_HIGH", "GOLDEN_CROSS"} & codes
                      or (snap.rsi14 and 40 <= snap.rsi14 <= 62 and snap.trend == "up")):
        horizon = "swing"
        reasons.append("uptrend with a fresh swing trigger")
        if rs60 and rs60 > 0:
            reasons.append(f"+{rs60:.0f}% vs SPY over ~3mo")
    elif ({"VOLUME_SURGE", "RSI_EXIT_OVERSOLD", "RSI_OVERSOLD", "BB_BREAKOUT_UP"} & codes
          and chg >= 3):
        horizon = "short_term"
        reasons.append("near-term momentum / catalyst in play")
    else:
        return None  # no clean, classifiable setup

    # supporting reasons from the fresh signals + the snapshot
    for s in sigs:
        if s["lean"] == "bull" and s["label"] not in reasons:
            reasons.append(s["label"])
    if snap.vol_ratio_20d and snap.vol_ratio_20d >= 1.5:
        reasons.append(f"volume {snap.vol_ratio_20d:.1f}x its 20-day average")
    if snap.pct_off_52w_high is not None and snap.pct_off_52w_high >= -5:
        reasons.append("within 5% of its 52-week high")

    # entry / stop / targets sized to the horizon. The top rung uses max() with
    # the 52-week high so a name already near its high still gets an increasing
    # ladder (never a target below a nearer one).
    hi = snap.high_52w or 0.0
    if horizon == "long_term":
        stop = min(snap.sma50 or (price - 2 * atr), price - 2 * atr)
        tgts = [price * 1.15, price * 1.30, max(price * 1.45, hi * 1.10)]
        hold = "months+"
    elif horizon == "swing":
        stop = min(snap.sma20 or (price - 1.5 * atr), price - 1.5 * atr)
        tgts = [price * 1.07, price * 1.14, max(price * 1.22, hi)]
        hold = "weeks"
    else:  # short_term
        stop = price - 1.0 * atr
        tgts = [price * 1.04, price * 1.08, price * 1.12]
        hold = "days"

    stop = round(stop, 4)
    risk = price - stop
    if risk <= 0:
        return None
    # clean, strictly-increasing ladder above entry
    targets = sorted({round(t, 4) for t in tgts if t > price})
    if not targets:
        return None
    rr1 = round((targets[0] - price) / risk, 1)

    # $100-minimum sizing (notional floor; show shares + $ at risk to the stop)
    shares = round(MIN_TRADE_USD / price, 4)
    risk_usd = round(shares * risk, 2)

    return {
        "symbol": sym, "horizon": horizon, "hold": hold,
        "cap": _cap_class((cheap or {}).get("market_cap")),
        "price": round(price, 4), "entry": round(price, 4), "stop": stop,
        "targets": targets, "rr1": rr1, "risk_pct": round(risk / price * 100, 1),
        "reasons": reasons[:6], "conviction": len(reasons),
        "rs60": round(rs60, 1) if rs60 is not None else None,
        "rs120": round(rs120, 1) if rs120 is not None else None,
        "trend": snap.trend, "rsi": round(snap.rsi14) if snap.rsi14 else None,
        "size_usd": MIN_TRADE_USD, "size_shares": shares, "risk_usd": risk_usd,
        "src": (cheap or {}).get("src"),
    }


def analyze_symbol(sym: str, bench: dict, cheap: dict | None = None) -> dict | None:
    _ensure_history(sym)
    snap = ta.compute(sym)
    if not snap.last_close:
        return None
    sig = signals.summarize(sym)
    closes = _closes(sym)
    rs = {}
    for n in _RS_WINDOWS:
        sret, bret = _ret_pct(closes, n), bench.get(n)
        rs[n] = round(sret - bret, 1) if (sret is not None and bret is not None) else None
    return _build_idea(sym, snap, sig, rs, cheap)


def scan(max_deep: int = 30) -> list[dict]:
    """Return ranked, horizon-tagged long ideas across the broad universe."""
    uni = gather_universe()
    if not uni:
        return []
    bench = _bench_returns()
    shortlist = _shortlist(uni, max_deep)
    ideas = []
    for s in shortlist:
        idea = analyze_symbol(s, bench, uni.get(s))
        if idea:
            ideas.append(idea)
    # rank: conviction first, then R:R
    ideas.sort(key=lambda i: (i["conviction"], i["rr1"]), reverse=True)
    return ideas


_HORIZON_HDR = {"short_term": "⚡ Short-term (days)",
                "swing": "📈 Swing (weeks)",
                "long_term": "🏛️ Long-term (months+)"}


def build_report(ideas: list[dict]) -> str:
    if not ideas:
        return ("No clean long setups across the scanned universe right now. "
                "The market may be mid-range — check back next scan.")
    from dk.analysis.perp import _fmt
    L = ["**Equity ideas — multi-horizon, logic-backed**",
         "Discovery, not instructions. Each carries its reasons and an invalidation (the stop). "
         "Sizing is the $100 floor — scale to your own risk.", ""]
    for hz in ("short_term", "swing", "long_term"):
        group = [i for i in ideas if i["horizon"] == hz]
        if not group:
            continue
        L.append(f"### {_HORIZON_HDR[hz]}")
        for i in group:
            rs = f" · RS {i['rs120']:+}% 6mo" if i.get("rs120") is not None else ""
            L.append(f"**{i['symbol']}** ({i['cap']} cap) — ${_fmt(i['price'])} · {i['trend']} trend"
                     f"{rs} · R:R {i['rr1']}:1 (risk {i['risk_pct']}%)")
            L.append(f"  - entry ${_fmt(i['entry'])} · stop ${_fmt(i['stop'])} · "
                     f"targets {' / '.join('$'+_fmt(t) for t in i['targets'])}")
            L.append(f"  - size: ${i['size_usd']:.0f} ≈ {i['size_shares']} sh "
                     f"(≈${i['risk_usd']:.2f} at risk to the stop)")
            L.append(f"  - why: {'; '.join(i['reasons'])}")
        L.append("")
    L.append("_Keyless technical + relative-strength read; no fundamentals/valuation. "
             "Long-term = durable trend + RS leadership, not a value call. Honor each stop._")
    return "\n".join(L)


if __name__ == "__main__":
    import io
    import sys
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    print(build_report(scan()))
