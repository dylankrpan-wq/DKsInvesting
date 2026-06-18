"""Scan all Blofin perps for setups with "leverage in my favor" — a tight stop
relative to the target (high R:R, low risk %), so size can be applied with
small, defined downside.

Two stages to stay cheap:
  1. one fetch_tickers call (~500 perps) -> filter by liquidity, rank by 24h
     volatility, keep the top `max_deep` movers (the only ones with tradeable
     structure).
  2. full perp.analyze() on that shortlist -> take each pair's better side
     (long vs short by R:R), keep the ones that clear min R:R and max risk %,
     rank by R:R.

Discovery, not signals: every row carries its side, entry/stop/target, R:R,
and invalidation so it's a setup to investigate, not an instruction. On-demand
only (dashboard button / CLI) — not on the fast timer.
"""
from __future__ import annotations
import json
import math
import time
from dk.config import load_watchlist
from dk.sources import crypto_deriv
from dk.analysis import perp


def _cfg() -> dict:
    return (load_watchlist().get("setup_scan") or {})


def cron_minute() -> int:
    return int(_cfg().get("cron_minute", 30))


def _trend_setup(a: dict, side: str, stop_mult: float = 1.2) -> dict | None:
    """TREND-FOLLOWING setup: a tight ATR stop in the trend direction + R-multiple
    extension targets. perp.analyze's built-in setups are RANGE/mean-reversion
    (buy support, target resistance) — in a trend that gives fake-high R:R on the
    counter-trend side (the fades that bleed) and sub-1 R:R with-trend. This builds
    the with-trend setup correctly: you risk a shallow ATR pullback to ride the
    continuation, targets at 1.5R / 3R / 4.5R."""
    last, atr = a.get("last"), a.get("atr_1h")
    if not last or not atr or atr <= 0:
        return None
    risk = stop_mult * atr
    if risk <= 0:
        return None
    if side == "long":
        stop = last - risk
        tps = [last + m * risk for m in (1.5, 3.0, 4.5)]
    else:
        stop = last + risk
        tps = [last - m * risk for m in (1.5, 3.0, 4.5)]
    tps = [t for t in tps if t > 0]
    if stop <= 0 or not tps:
        return None
    return {
        "entry": round(last, 6), "stop": round(stop, 6),
        "risk_pct": round(risk / last * 100, 1), "rr1": 1.5,
        "tps": [{"level": round(t, 6), "r": round(abs(t - last) / risk, 1),
                 "pct": round((t - last) / last * 100, 1), "basis": "R-mult"} for t in tps],
    }


def scan(top_n: int = 10, max_deep: int = 40, min_vol_usd: float = 1_000_000,
         max_vol_range: float = 60.0, min_rr: float = 1.5, max_risk_pct: float = 6.0,
         min_confluence: int = 3, stop_mult: float = 1.2, side: str = "both") -> list[dict]:
    """Return TREND-ALIGNED, confluence-gated setups, ranked by conviction.

    Quality over quantity (the scorecard showed R:R-only / max-volatility selection
    bleeds): (1) liquid universe with a tradeable BUT NOT insane range — extreme
    volatility = manipulated low-floats, skipped; (2) only the side that agrees
    with the 1H trend (no fading); (3) a confluence score (trend + funding tailwind
    + R:R + tight risk + volume + room to target) — only setups clearing
    min_confluence qualify. side: 'both' | 'long' | 'short'."""
    tickers = crypto_deriv.fetch_tickers("SWAP")
    if not tickers:
        return []

    # Stage 1: LIQUID names with a real-but-sane range. Rank by a quality blend
    # (range capped + weighted by liquidity), NOT raw max volatility.
    cands = []
    for t in tickers:
        if t["quote_vol_usd"] < min_vol_usd or not t["low24h"]:
            continue
        vr = (t["high24h"] - t["low24h"]) / t["low24h"] * 100.0
        if vr > max_vol_range:   # too volatile -> too manipulated -> skip
            continue
        quality = min(vr, 25.0) * (1 + math.log10(t["quote_vol_usd"] / min_vol_usd + 1.0))
        cands.append((quality, t))
    cands.sort(key=lambda x: x[0], reverse=True)
    shortlist = [t for _, t in cands[:max_deep]]

    # Stage 2: deep structure -> trend-align -> confluence-gate
    out: list[dict] = []
    for t in shortlist:
        a = perp.analyze(t["inst_id"], ticker=t)
        if not a:
            continue
        # --- trend (1H): only trade WITH it; skip choppy/mixed ---
        vs_ma, chg = a.get("vs_ma_pct"), a.get("chg_24h_pct")
        if vs_ma is None or chg is None:
            continue
        if vs_ma > 0 and chg > 0:
            trend = "long"
        elif vs_ma < 0 and chg < 0:
            trend = "short"
        else:
            continue  # no clean trend -> no call-out (this kills the fade trades)
        if side != "both" and side != trend:
            continue
        # TREND-FOLLOWING setup (tight ATR stop + R-multiple extension), NOT the
        # range setup — that's the whole fix for the counter-trend-fade bleed.
        s = _trend_setup(a, trend, stop_mult=stop_mult)
        if not s or s["risk_pct"] > max_risk_pct:
            continue

        # --- confluence (of 6): trend is factor 1; stack the rest ---
        fund = a.get("funding_pct")
        tailwind = (fund is not None and ((trend == "long" and fund < 0)
                                          or (trend == "short" and fund > 0)))
        conf = 1
        reasons = [f"{trend} with the 1H trend ({vs_ma:+}% vs MA20, {chg:+}% 24h)"]
        if tailwind:
            conf += 1
            reasons.append("funding pays your side")
        if abs(vs_ma) >= 3:
            conf += 1
            reasons.append("strong trend (>3% from MA20)")
        if s["risk_pct"] <= 2.5:
            conf += 1
            reasons.append(f"contained {s['risk_pct']}% risk")
        if (a.get("last_vol_x") or 0) >= 1.5:
            conf += 1
            reasons.append(f"volume {a['last_vol_x']}x")
        off_hi, abv_lo = a.get("off_high_pct"), a.get("above_low_pct")
        if trend == "long" and off_hi is not None and off_hi <= -3:
            conf += 1
            reasons.append("room below the 24h high")
        elif trend == "short" and abv_lo is not None and abv_lo >= 3:
            conf += 1
            reasons.append("room above the 24h low")
        if conf < min_confluence:
            continue

        out.append({
            "inst_id": a["inst_id"], "side": trend, "rr1": s["rr1"],
            "risk_pct": s["risk_pct"], "entry": s["entry"], "stop": s["stop"],
            "tps": s.get("tps", []), "confluence": conf, "conf_reasons": reasons,
            "phase": a.get("phase"), "micro_pos": a.get("micro_pos"),
            "chg_24h_pct": chg, "off_high_pct": off_hi,
            "funding_pct": fund, "funding_tailwind": tailwind,
            "invalidation": a.get(f"invalidation_{trend}"),
            "atr_pct": a.get("atr_pct"), "vs_ma_pct": vs_ma,
            "above_low_pct": abv_lo, "range24_pct": a.get("range24_pct"),
            "last_vol_x": a.get("last_vol_x"),
        })
        time.sleep(0.08)  # be polite to the public endpoint

    # rank by conviction (confluence) first, then R:R
    out.sort(key=lambda r: (r["confluence"], r["rr1"]), reverse=True)
    return out[:top_n]


def build_report(rows: list[dict]) -> str:
    if not rows:
        return ("No setups clear the bar right now (tight stop + good R:R on a "
                "liquid, volatile perp). The market may be mid-range — check back.")
    from dk.analysis.perp import _fmt

    def _tp(r, i):
        tps = r.get("tps") or []
        return f"${_fmt(tps[i]['level'])} ({tps[i]['r']}R)" if i < len(tps) else "—"

    L = ["**Leverage-in-my-favor scan** — tight stop relative to target, ranked by R:R.",
         "Discovery, not instructions. Each is a setup to investigate; honor the invalidation.",
         "",
         "| Pair | Side | Risk | Entry | Stop | TP1 | TP2 | TP3 | Why |",
         "|------|------|-----:|------|------|-----|-----|-----|-----|"]
    for r in rows:
        tw = " ⚡fund" if r["funding_tailwind"] else ""
        why = f"{r.get('phase','')}{tw}"
        L.append(f"| {r['inst_id']} | {r['side']} | {r['risk_pct']}% | "
                 f"${_fmt(r['entry'])} | ${_fmt(r['stop'])} | "
                 f"{_tp(r,0)} | {_tp(r,1)} | {_tp(r,2)} | {why} |")
    L += ["", "_TPs are structural levels on the profit side (R = reward/risk multiple); "
          "where no structural level exists that far, the rung is an R-multiple extension. "
          "⚡fund = funding pays your side. Low-float perps — manipulation/liquidation risk on "
          "leverage; no order-book/OI/IV here. Invalidation per-setup: close/hold past the stop._"]
    return "\n".join(L)


def _fmt_p(p):
    from dk.analysis.perp import _fmt
    return _fmt(p)


def _setup_msg(r: dict) -> str:
    """Setup text — used both as the alert body and the chart caption."""
    arrow = "🟢" if r["side"] == "long" else "🔴"
    tw = " ⚡fund" if r.get("funding_tailwind") else ""
    tps = r.get("tps") or []
    tp_str = " / ".join(f"${_fmt_p(tp['level'])}" for tp in tps) or "—"
    conf = r.get("confluence")
    badge = f" · ⭐{conf}/6 confluence" if conf else ""
    why = "; ".join((r.get("conf_reasons") or [])[:3])
    return (f"🎯 {arrow} {r['side'].upper()} {r['inst_id']} {r['rr1']}:1 "
            f"(risk {r['risk_pct']}%){badge} — entry ${_fmt_p(r['entry'])}, "
            f"stop ${_fmt_p(r['stop'])}, TP1/2/3 {tp_str}{tw}"
            + (f"\nwhy: {why}" if why else ""))


def scan_and_alert(push: bool = True) -> dict:
    """Scheduled entry. Scans a WIDE net at a lower 'track' bar, then:
      • PUSHES the top few that clear the HIGH push bar -> SETUP_SCAN alerts
        (phone + chart + live TP/stop tracking), as before.
      • silently TRACKS the rest -> SETUP_TRACK rows (never pushed, sms_sent=1),
        so the call-out scorecard scores 10-20/day and we learn what actually
        wins without spamming the phone.
    Tracking runs even with no phone channel; only the push needs one."""
    from dk.store import db as store
    cfg = _cfg()
    if not cfg.get("enabled", True):
        return {"skipped": "disabled"}
    from dk.notify import sms
    phone = sms.is_configured()

    # Trend-aligned, confluence-gated, trend-following research set (quality first).
    track_rows = scan(top_n=int(cfg.get("track_universe", 12)),
                      max_deep=int(cfg.get("track_deep", 40)),
                      min_vol_usd=float(cfg.get("min_vol_usd", 1_000_000)),
                      max_vol_range=float(cfg.get("max_vol_range", 60.0)),
                      max_risk_pct=float(cfg.get("track_max_risk_pct", 6.0)),
                      min_confluence=int(cfg.get("min_confluence", 3)),
                      stop_mult=float(cfg.get("stop_mult", 1.2)),
                      side=cfg.get("side", "both"))
    if not track_rows:
        return {"scanned": True, "pushed": 0, "tracked": 0,
                "note": "no trend-aligned, confluent setups right now"}

    push_min_conf = int(cfg.get("push_min_confluence", 4))
    push_n = int(cfg.get("top_n", 2))
    track_n = int(cfg.get("track_top_n", 4))
    push_cd = int(cfg.get("cooldown_hours", 6))
    track_cd = int(cfg.get("track_cooldown_hours", 3))

    # PUSH only the A+ setups (high confluence); everything else is tracked silently.
    push_pool = [r for r in track_rows if r["confluence"] >= push_min_conf]

    new = 0          # SETUP_SCAN (pushed) count
    tracked = 0      # SETUP_TRACK (silent) count
    pushed_ids: set[str] = set()
    registered = []  # (alert_id, row) for the pushed ones — tracked live after conn closes
    store.init_db()
    with store.conn() as c:
        # PUSH: top push_n standouts, fresh per the push cooldown
        for r in push_pool:
            if new >= push_n:
                break
            recent = c.execute(
                """SELECT 1 FROM alerts WHERE symbol=? AND kind='SETUP_SCAN'
                   AND created_at >= datetime('now', ?) LIMIT 1""",
                (r["inst_id"], f"-{push_cd} hours")).fetchone()
            if recent:
                continue
            cur = c.execute(
                "INSERT INTO alerts (symbol, kind, message, payload) VALUES (?,?,?,?)",
                (r["inst_id"], "SETUP_SCAN", _setup_msg(r), json.dumps(r)))
            registered.append((cur.lastrowid, r))
            pushed_ids.add(r["inst_id"])
            new += 1
        # TRACK: up to track_n more (not already pushed), fresh per the track
        # cooldown, as silent SETUP_TRACK rows (sms_sent=1 so the digest skips them).
        for r in track_rows:
            if tracked >= track_n:
                break
            if r["inst_id"] in pushed_ids:
                continue
            recent = c.execute(
                """SELECT 1 FROM alerts WHERE symbol=? AND kind IN ('SETUP_SCAN','SETUP_TRACK')
                   AND created_at >= datetime('now', ?) LIMIT 1""",
                (r["inst_id"], f"-{track_cd} hours")).fetchone()
            if recent:
                continue
            c.execute(
                "INSERT INTO alerts (symbol, kind, message, payload, sms_sent) VALUES (?,?,?,?,1)",
                (r["inst_id"], "SETUP_TRACK", _setup_msg(r), json.dumps(r)))
            tracked += 1

    # Register each PUSHED setup as a live tracked signal (separate conn, after close)
    try:
        from dk.analysis import perp_tracker
        for aid, r in registered:
            perp_tracker.register_signal(aid, r)
    except Exception as e:
        print(f"[setup_scan] tracker registration failed: {e}")

    # Chart-image push: render the annotated chart per fresh setup and send it as
    # a Telegram photo (caption carries the levels). On success, mark the alert
    # sms_sent=1 so the text digest below doesn't also send it. If image export
    # is unavailable (no kaleido/Chrome), the setup falls through to the text digest.
    charts_pushed = 0
    if push and phone and registered and cfg.get("push_charts", True):
        try:
            from dk.charts import perp_fig
            for aid, r in registered:
                png = perp_fig.chart_png(r["inst_id"], overlay=r["side"].capitalize())
                if png and sms.send_photo(png, _setup_msg(r)):
                    with store.conn() as c:
                        c.execute("UPDATE alerts SET sms_sent=1 WHERE id=?", (aid,))
                    charts_pushed += 1
        except Exception as e:
            print(f"[setup_scan] chart push failed: {e}")

    summary = {"scanned": True, "candidates": len(track_rows), "pushed": new,
               "tracked": tracked, "charts_pushed": charts_pushed}
    if push and phone and new:
        try:
            summary["push"] = sms.push_digest()
        except Exception as e:
            print(f"[setup_scan] push failed: {e}")
            summary["push"] = {"error": str(e)}
    return summary


if __name__ == "__main__":
    import io
    import sys
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    side = sys.argv[1] if len(sys.argv) > 1 else "both"
    print(build_report(scan(side=side)))
