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
import time
from dk.sources import crypto_deriv
from dk.analysis import perp


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
            "target1": s["targets"][0] if s.get("targets") else None,
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
    L = ["**Leverage-in-my-favor scan** — tight stop relative to target, ranked by R:R.",
         "Discovery, not instructions. Each is a setup to investigate; honor the invalidation.",
         "",
         "| Pair | Side | R:R | Risk | Entry | Stop | Target | Why |",
         "|------|------|----:|-----:|------|------|--------|-----|"]
    for r in rows:
        from dk.analysis.perp import _fmt
        tw = " ⚡fund" if r["funding_tailwind"] else ""
        why = f"{r.get('phase','')}, {r.get('micro_pos','')}{tw}"
        L.append(f"| {r['inst_id']} | {r['side']} | {r['rr1']}:1 | {r['risk_pct']}% | "
                 f"${_fmt(r['entry'])} | ${_fmt(r['stop'])} | ${_fmt(r['target1'])} | {why} |")
    L += ["", "_⚡fund = funding pays your side. Low-float perps — manipulation/liquidation "
          "risk on leverage; no order-book/OI/IV in this data. Invalidation is per-setup: "
          "close/hold past the stop level._"]
    return "\n".join(L)


if __name__ == "__main__":
    import io
    import sys
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    side = sys.argv[1] if len(sys.argv) > 1 else "both"
    print(build_report(scan(side=side)))
