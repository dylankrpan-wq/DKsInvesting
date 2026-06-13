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
import time
from dk.config import load_watchlist
from dk.sources import crypto_deriv
from dk.analysis import perp


def _cfg() -> dict:
    return (load_watchlist().get("setup_scan") or {})


def cron_minute() -> int:
    return int(_cfg().get("cron_minute", 30))


def scan(top_n: int = 10, max_deep: int = 25, min_vol_usd: float = 300_000,
         min_rr: float = 2.5, max_risk_pct: float = 4.0,
         side: str = "both") -> list[dict]:
    """Return ranked setups (best R:R first). side: 'both' | 'long' | 'short'."""
    tickers = crypto_deriv.fetch_tickers("SWAP")
    if not tickers:
        return []

    # Stage 1: liquid + most volatile (a real working range = tradeable structure)
    cands = []
    for t in tickers:
        if t["quote_vol_usd"] < min_vol_usd or not t["low24h"]:
            continue
        vol_range = (t["high24h"] - t["low24h"]) / t["low24h"] * 100.0
        cands.append((vol_range, t))
    cands.sort(key=lambda x: x[0], reverse=True)
    shortlist = [t for _, t in cands[:max_deep]]

    # Stage 2: deep structure, keep the better side if it clears the bars
    out: list[dict] = []
    for t in shortlist:
        a = perp.analyze(t["inst_id"], ticker=t)
        if not a:
            continue
        options = []
        for sd in ("long", "short"):
            if side != "both" and side != sd:
                continue
            s = a.get(sd)
            if s and s.get("rr1") is not None and s.get("risk_pct") is not None:
                if s["rr1"] >= min_rr and s["risk_pct"] <= max_risk_pct:
                    options.append((sd, s))
        if not options:
            continue
        sd, s = max(options, key=lambda o: o[1]["rr1"])
        # funding tailwind: long wants negative funding, short wants positive
        fund = a.get("funding_pct")
        tailwind = (fund is not None and ((sd == "long" and fund < 0)
                                          or (sd == "short" and fund > 0)))
        out.append({
            "inst_id": a["inst_id"], "side": sd, "rr1": s["rr1"],
            "risk_pct": s["risk_pct"], "entry": s["entry"], "stop": s["stop"],
            "tps": s.get("tps", []),
            "phase": a.get("phase"), "micro_pos": a.get("micro_pos"),
            "chg_24h_pct": a.get("chg_24h_pct"), "off_high_pct": a.get("off_high_pct"),
            "funding_pct": fund, "funding_tailwind": tailwind,
            "invalidation": a.get(f"invalidation_{sd}"),
        })
        time.sleep(0.08)  # be polite to the public endpoint

    out.sort(key=lambda r: r["rr1"], reverse=True)
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


def scan_and_alert(push: bool = True) -> dict:
    """Scheduled entry: scan with a HIGH bar (only standout setups), emit a
    SETUP_SCAN alert per fresh one (per-symbol cooldown), then push the phone.
    No-op when disabled or no phone channel."""
    from dk.store import db as store
    cfg = _cfg()
    if not cfg.get("enabled", True):
        return {"skipped": "disabled"}
    from dk.notify import sms
    if not sms.is_configured():
        return {"skipped": "no phone channel"}

    rows = scan(top_n=int(cfg.get("top_n", 2)),
                min_rr=float(cfg.get("min_rr", 4.0)),
                max_risk_pct=float(cfg.get("max_risk_pct", 3.0)),
                side=cfg.get("side", "both"))
    if not rows:
        return {"scanned": True, "alerts": 0, "note": "no standout setups"}

    cooldown_h = int(cfg.get("cooldown_hours", 6))
    new = 0
    store.init_db()
    with store.conn() as c:
        for r in rows:
            recent = c.execute(
                """SELECT 1 FROM alerts WHERE symbol=? AND kind='SETUP_SCAN'
                   AND created_at >= datetime('now', ?) LIMIT 1""",
                (r["inst_id"], f"-{cooldown_h} hours")).fetchone()
            if recent:
                continue
            arrow = "🟢" if r["side"] == "long" else "🔴"
            tw = " ⚡fund" if r["funding_tailwind"] else ""
            tps = r.get("tps") or []
            tp_str = " / ".join(f"${_fmt_p(tp['level'])}" for tp in tps) or "—"
            msg = (f"🎯 {arrow} {r['side'].upper()} {r['inst_id']} {r['rr1']}:1 "
                   f"(risk {r['risk_pct']}%) — entry ${_fmt_p(r['entry'])}, "
                   f"stop ${_fmt_p(r['stop'])}, TP1/2/3 {tp_str}{tw}")
            c.execute(
                "INSERT INTO alerts (symbol, kind, message, payload) VALUES (?,?,?,?)",
                (r["inst_id"], "SETUP_SCAN", msg, json.dumps(r)))
            new += 1

    summary = {"scanned": True, "candidates": len(rows), "alerts": new}
    if push and new:
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
