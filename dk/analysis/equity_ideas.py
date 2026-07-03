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

Keyless: price/volume technicals + relative strength. No fundamentals and no
news/catalyst feed (a later, data-keyed upgrade), so long-term ideas are framed
on durable trend + relative-strength leadership, not valuation. Discovery, not
instructions — every idea carries its reasons and an invalidation (the stop).
"""
from __future__ import annotations
import json
import math
import sqlite3
from dk.config import DB_PATH, load_watchlist
from dk.sources import market_movers, prices_yfinance
from dk.indicators import ta, signals
from dk import llm

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
    rets = {n: _ret_pct(closes, n) for n in _RS_WINDOWS}
    if len(closes) <= max(_RS_WINDOWS):
        print(f"[equity_ideas] WARN: {BENCH} history only {len(closes)} bars "
              f"(< {max(_RS_WINDOWS) + 1} needed for RS) — relative strength limited; "
              f"long-term ideas (which require measured RS) will be suppressed.")
    return rets


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
    # Always cover the tech/AI/energy sector universe (config/sector_watch.yaml)
    # so those names are scanned every run, not only when they're daily movers.
    try:
        import yaml
        from dk.config import CONFIG_DIR
        _sw = CONFIG_DIR / "sector_watch.yaml"
        if _sw.exists():
            with open(_sw, "r", encoding="utf-8") as _f:
                _scfg = yaml.safe_load(_f) or {}
            for _names in (_scfg.get("sectors") or {}).values():
                for _s in (_names or []):
                    uni.setdefault(str(_s).upper(),
                                   {"price": None, "chg_pct": None, "volume": None,
                                    "market_cap": None, "src": "sector"})
    except Exception as e:
        print(f"[equity_ideas] sector universe: {e}")
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
    # Always deep-analyze watchlist AND sector-universe names (tech/AI/energy),
    # then fill remaining slots with the most active market-wide movers.
    watch = [s for s, d in uni.items() if d.get("src") in ("watchlist", "sector")]
    movers = [(s, d) for s, d in uni.items() if d.get("src") not in ("watchlist", "sector")]

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

    # Long-bias only (investment ideas). A bare "above the 50-day MA" is NOT enough
    # (a downtrending name a hair above its 50-MA isn't bullish) — pair it with an
    # actual bull trigger, or require a bull lean / up trend.
    _bull_triggers = {"MACD_BULL_CROSS", "SMA50_RECLAIM", "BB_BREAKOUT_UP",
                      "NEW_52W_HIGH", "GOLDEN_CROSS", "RSI_EXIT_OVERSOLD", "RSI_OVERSOLD"}
    bullish = (sig["net_lean"] == "bull" or snap.trend == "up"
               or (above50 and bool(_bull_triggers & codes)))
    if not bullish:
        return None

    swing_trig = bool({"MACD_BULL_CROSS", "SMA50_RECLAIM", "BB_BREAKOUT_UP",
                       "NEW_52W_HIGH", "GOLDEN_CROSS"} & codes)
    short_trig = bool({"VOLUME_SURGE", "RSI_EXIT_OVERSOLD", "RSI_OVERSOLD",
                       "BB_BREAKOUT_UP"} & codes)
    chg_min = float(_cfg().get("short_chg_min", 3.0))

    reasons: list[str] = []
    # Horizon by durability: 200-day uptrend leader -> long; above-50 trend/RS
    # leader -> swing; meaningful move today in an uptrend -> short. long_term
    # REQUIRES measured RS (fail-closed). A shallow pullback (below the 20-MA but
    # still 50>200 above the 200-MA) still counts long-term — that's a dip entry.
    if above200 and ma50_gt_200 and rs120 is not None and rs120 >= 0:
        horizon = "long_term"
        reasons.append("uptrend above a rising 200-day MA (50>200), fully stacked"
                       if stacked else "long-term uptrend (50>200), buying a pullback")
        if rs120 > 0:
            reasons.append(f"+{rs120:.0f}% vs SPY over ~6mo (relative-strength leader)")
    elif above50 and (swing_trig
                      or (snap.rsi14 and 40 <= snap.rsi14 <= 62 and snap.trend == "up")
                      or (rs60 and rs60 > 0)):
        horizon = "swing"
        reasons.append("uptrend with a fresh swing trigger" if swing_trig
                       else "above the 50-day MA, leading on 3-month relative strength")
        if rs60 and rs60 > 0:
            reasons.append(f"+{rs60:.0f}% vs SPY over ~3mo")
    elif chg >= chg_min and (short_trig or above50):
        horizon = "short_term"
        reasons.append(f"up {chg:.0f}% today with near-term momentum")
        if rs60 and rs60 > 0:
            reasons.append(f"+{rs60:.0f}% vs SPY over ~3mo")
    else:
        return None  # no clean, classifiable setup

    # supporting reasons: fresh signals (bull OR neutral, e.g. a volume surge) + snapshot
    for s in sigs:
        if s["lean"] != "bear" and s["label"] not in reasons:
            reasons.append(s["label"])
    if snap.vol_ratio_20d and snap.vol_ratio_20d >= 1.5:
        reasons.append(f"volume {snap.vol_ratio_20d:.1f}x its 20-day average")
    if snap.pct_off_52w_high is not None and snap.pct_off_52w_high >= -5:
        reasons.append("within 5% of its 52-week high")

    # entry / stop / targets sized to the horizon. The top rung blends in the
    # 52-week high ONLY when the name is actually near it (else a deep-drawdown
    # name would get a +50% target inconsistent with a "weeks" holding period).
    # Volatility-scaled (ATR) stops per horizon — NOT a stop way down at the 50-MA,
    # which gave 20-40% risk on names that had run far above it (penalizing the
    # strongest trends). The max_risk_pct cap then drops anything still too wide.
    hi = snap.high_52w or 0.0
    near_high = snap.pct_off_52w_high is not None and snap.pct_off_52w_high >= -10
    if horizon == "long_term":
        stop = price - 2.5 * atr
        top = max(price * 1.45, hi * 1.10) if near_high else price * 1.45
        tgts = [price * 1.15, price * 1.30, top]
        hold = "months+"
    elif horizon == "swing":
        stop = price - 1.8 * atr
        top = max(price * 1.22, hi) if near_high else price * 1.22
        tgts = [price * 1.07, price * 1.14, top]
        hold = "weeks"
    else:  # short_term
        stop = price - 1.2 * atr
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

    # Sizing: $100 is the MINIMUM per trade, in WHOLE shares (broker-universal —
    # not every broker does fractional). ceil(100/price) => notional >= $100 (1
    # share for any name over $100). frac_alt is the fractional equivalent if the
    # broker supports it. risk_usd is the $ to the stop on the whole-share size.
    shares = max(1, math.ceil(MIN_TRADE_USD / price))
    size_usd = round(shares * price, 2)
    risk_usd = round(shares * risk, 2)
    frac_alt = round(MIN_TRADE_USD / price, 4)

    shown = reasons[:6]
    return {
        "symbol": sym, "horizon": horizon, "hold": hold,
        "cap": _cap_class((cheap or {}).get("market_cap")),
        "price": round(price, 4), "entry": round(price, 4), "stop": stop,
        "targets": targets, "rr1": rr1, "risk_pct": round(risk / price * 100, 1),
        "reasons": shown, "conviction": len(shown),
        "rs60": round(rs60, 1) if rs60 is not None else None,
        "rs120": round(rs120, 1) if rs120 is not None else None,
        "trend": snap.trend, "rsi": round(snap.rsi14) if snap.rsi14 else None,
        "size_usd": size_usd, "size_shares": shares, "size_frac": frac_alt,
        "risk_usd": risk_usd, "src": (cheap or {}).get("src"),
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


_LAST_SCAN_STATS: dict = {}


def scan(max_deep: int = 30) -> list[dict]:
    """Return ranked, horizon-tagged long ideas across the broad universe. Also
    records _LAST_SCAN_STATS so callers can tell a quiet market from a blocked
    price source (history_short = symbols that yielded no idea for lack of bars)."""
    global _LAST_SCAN_STATS
    uni = gather_universe()
    if not uni:
        _LAST_SCAN_STATS = {"universe": 0, "analyzed": 0, "history_short": 0,
                            "bench_ok": False, "ideas": 0}
        return []
    bench = _bench_returns()
    bench_ok = any(v is not None for v in bench.values())
    shortlist = _shortlist(uni, max_deep)
    ideas = []
    history_short = 0
    for s in shortlist:
        try:  # one bad symbol's data must never abort the whole scan
            idea = analyze_symbol(s, bench, uni.get(s))
        except Exception as e:
            print(f"[equity_ideas] analyze {s}: {e}")
            idea = None
        if idea is None and len(_closes(s)) < 200:
            history_short += 1  # no idea AND too few bars => likely a blocked fetch
        if idea:
            ideas.append(idea)
    cfg = _cfg()                                 # quality bars: R:R floor + stop cap
    min_rr = float(cfg.get("min_rr", 1.0))
    max_risk = float(cfg.get("max_risk_pct", 12.0))
    ideas = [i for i in ideas if i["rr1"] >= min_rr and i["risk_pct"] <= max_risk]
    ideas.sort(key=lambda i: (i["conviction"], i["rr1"]), reverse=True)
    _LAST_SCAN_STATS = {"universe": len(uni), "analyzed": len(shortlist),
                        "history_short": history_short, "bench_ok": bench_ok,
                        "ideas": len(ideas)}
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
         "Size is the $100 minimum in whole shares — scale to your own risk.", ""]
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
            L.append(f"  - size: {i['size_shares']} sh ≈ ${i['size_usd']:.0f} "
                     f"($100 min, whole shares) · ≈${i['risk_usd']:.2f} at risk to the stop")
            L.append(f"  - why: {'; '.join(i['reasons'])}")
        L.append("")
    L.append("_Keyless technical + relative-strength read; no fundamentals/valuation. "
             "Long-term = durable trend + RS leadership, not a value call. Honor each stop._")
    return "\n".join(L)


# ---- theses + scheduled scan/push/track ---------------------------------

def _cfg() -> dict:
    return (load_watchlist().get("equity_ideas") or {})


_THESIS_SYSTEM = """You are an equity analyst writing a tight, logic-backed thesis on ONE stock idea for an experienced trader. You are given a JSON block of MEASURED technicals: price, moving-average structure (20/50/200), RSI, MACD, 52-week range, volume ratio, relative strength vs SPY, the detected setup, the assigned horizon, entry/stop/targets, and a $100-floor position size.

Rules:
- Use ONLY numbers present in the JSON. Never invent a price, level, fundamental, earnings number, or catalyst. You have NO fundamentals/valuation/earnings data here — this is a technical + relative-strength read; say so plainly.
- State the HORIZON (short-term = days / swing = weeks / long-term = months+) and frame the thesis to that holding period.
- Give the LOGIC: what the trend structure and relative strength say, and the single clearest reason the setup could work.
- State the INVALIDATION explicitly (the stop) and the targets with the R:R.
- Mention the size as the $100 MINIMUM in whole shares (the trader scales up to their own risk).
- If you cannot ground a statement in a JSON field, omit it. Do NOT name a sector theme, news event, product, earnings result, or macro driver — none are provided; the only "catalyst" here is the measured technical trigger (volume / RSI / breakout / MA structure).
- ~120 words, concrete, no hype, no emoji. End with the one thing to watch.
Discovery, not instructions — never say "buy"; say what the evidence supports and what would flip it."""


def template_thesis(idea: dict) -> str:
    """Deterministic, grounded thesis (free; the Claude fallback and offline path)."""
    from dk.analysis.perp import _fmt
    hz = {"short_term": "short-term (days)", "swing": "swing (weeks)",
          "long_term": "long-term (months+)"}.get(idea["horizon"], idea["horizon"])
    tgts = " / ".join("$" + _fmt(x) for x in idea["targets"])
    rs = (f" Relative strength vs SPY: {idea['rs120']:+}% over ~6mo." if idea.get("rs120") is not None else "")
    return (f"{idea['symbol']} — {hz} long idea ({idea['cap']} cap), {idea['trend']} trend.\n"
            f"Logic: {'; '.join(idea['reasons'])}.{rs}\n"
            f"Plan: enter ${_fmt(idea['entry'])}, stop ${_fmt(idea['stop'])} (invalidation), "
            f"targets {tgts} — R:R {idea['rr1']}:1, risk {idea['risk_pct']}%.\n"
            f"Size: {idea['size_shares']} sh ≈ ${idea['size_usd']:.0f} ($100 minimum, "
            f"whole shares; ≈${idea['risk_usd']:.2f} at risk). Technical + relative-strength "
            f"read, no fundamentals. Watch the stop.")


def claude_thesis(idea: dict) -> str:
    """Nuanced Claude thesis grounded in the idea's measured data; template fallback."""
    prompt = ("Write the thesis from this idea JSON:\n\n```json\n"
              + json.dumps(idea, sort_keys=True, default=str) + "\n```")
    res = llm.complete(prompt, system=_THESIS_SYSTEM,
                       model=_cfg().get("model") or llm.DEFAULT_MODEL,
                       max_tokens=900, adaptive_thinking=True)
    if res and res.get("text"):
        return res["text"]
    return template_thesis(idea)


def _setup_msg(idea: dict) -> str:
    """One-block phone summary for an idea (record + the concise alert line)."""
    from dk.analysis.perp import _fmt
    hz = {"short_term": "⚡ short-term", "swing": "📈 swing",
          "long_term": "🏛️ long-term"}.get(idea["horizon"], idea["horizon"])
    tgts = " / ".join("$" + _fmt(x) for x in idea["targets"])
    return (f"💡 {idea['symbol']} ({idea['cap']} cap) — {hz} LONG idea\n"
            f"entry ${_fmt(idea['entry'])} · stop ${_fmt(idea['stop'])} · targets {tgts} · "
            f"R:R {idea['rr1']}:1 (risk {idea['risk_pct']}%)\n"
            f"size {idea['size_shares']} sh ≈ ${idea['size_usd']:.0f} ($100 min) · "
            f"≈${idea['risk_usd']:.2f} risk\n"
            f"why: {'; '.join(idea['reasons'][:3])}")


def scan_and_alert(push: bool = True) -> dict:
    """Scheduled entry. Scans the broad universe, PUSHES the top few ideas (each
    with a Claude thesis) to the phone, and silently TRACKS the rest as
    EQUITY_IDEA_TRACK rows for the scorecard. Trading-day gated; per-symbol
    cooldown so a name isn't re-pitched daily. Tracking runs even with no phone."""
    from dk.store import db as store
    from dk.util import session
    cfg = _cfg()
    if not cfg.get("enabled", True):
        return {"skipped": "disabled"}
    if not session.is_trading_day():
        return {"skipped": "not a trading day"}
    from dk.notify import sms
    phone = sms.is_configured()

    ideas = scan(max_deep=int(cfg.get("max_deep", 30)))
    ideas = [i for i in ideas if i["conviction"] >= int(cfg.get("min_conviction", 3))]
    if not ideas:
        # scan_stats distinguishes a genuinely quiet market from a blocked price
        # source (history_short high / bench_ok False) instead of a bare "no ideas".
        return {"scanned": True, "pushed": 0, "tracked": 0,
                "note": "no ideas clear the bar", "scan_stats": _LAST_SCAN_STATS}

    push_n = int(cfg.get("push_top_n", 3))
    track_n = int(cfg.get("track_top_n", 12))
    cd = int(cfg.get("cooldown_hours", 24))
    push_min = int(cfg.get("push_min_conviction", 4))  # only A+ ideas reach the phone
    push_pool = [i for i in ideas if i["conviction"] >= push_min]

    def _fresh(c, sym) -> bool:
        return not c.execute(
            """SELECT 1 FROM alerts WHERE symbol=? AND kind IN ('EQUITY_IDEA','EQUITY_IDEA_TRACK')
               AND created_at >= datetime('now', ?) LIMIT 1""",
            (sym, f"-{cd} hours")).fetchone()

    pushed_ideas: list[dict] = []
    tracked = 0
    pushed_ids: set[str] = set()
    store.init_db()
    with store.conn() as c:
        for idea in push_pool:  # PUSH set: A+ only — reserve ids; the EQUITY_IDEA
            if len(pushed_ideas) >= push_n:  # row is written AFTER a successful send
                break
            if not _fresh(c, idea["symbol"]):
                continue
            pushed_ideas.append(idea)
            pushed_ids.add(idea["symbol"])
        for idea in ideas:  # TRACK set: next track_n fresh, silent (write-on-detect)
            if tracked >= track_n:
                break
            if idea["symbol"] in pushed_ids or not _fresh(c, idea["symbol"]):
                continue
            c.execute(
                "INSERT INTO alerts (symbol, kind, message, payload, sms_sent) VALUES (?,?,?,?,1)",
                (idea["symbol"], "EQUITY_IDEA_TRACK", _setup_msg(idea), json.dumps(idea)))
            tracked += 1

    # Push a grounded thesis per pushed idea, then RECORD the EQUITY_IDEA row only
    # on a successful send (or always, when phone push is off) — so a failed send
    # doesn't burn the 24h cooldown with nothing delivered to the phone.
    do_push = push and phone and cfg.get("send_to_phone", True)
    use_claude = llm.is_available()
    sent = 0
    recorded = 0
    for idea in pushed_ideas:
        delivered = True
        if do_push:
            delivered = False
            try:
                txt = claude_thesis(idea) if use_claude else template_thesis(idea)
                delivered = bool(sms.send_summary(txt))
                if delivered:
                    sent += 1
            except Exception as e:
                print(f"[equity_ideas] thesis push {idea['symbol']}: {e}")
        if delivered:  # send succeeded, or record-only (no-phone) mode
            with store.conn() as c:
                c.execute(
                    "INSERT INTO alerts (symbol, kind, message, payload, sms_sent) VALUES (?,?,?,?,1)",
                    (idea["symbol"], "EQUITY_IDEA", _setup_msg(idea), json.dumps(idea)))
            recorded += 1
    return {"scanned": True, "pushed": recorded, "tracked": tracked,
            "theses_sent": sent, "candidates": len(ideas), "scan_stats": _LAST_SCAN_STATS}


if __name__ == "__main__":
    import io
    import sys
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    print(build_report(scan()))
