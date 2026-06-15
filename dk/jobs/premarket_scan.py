"""Pre-market US-equity gap scan -> phone.

Runs every ~15 min but only during the pre-market window (gated by
dk.util.session). Emits a PREMARKET_GAP alert per fresh gapper (watchlist names
at a lower threshold; big market movers at a higher one), with a per-symbol
cooldown, then pushes the digest. Quiet outside pre-market and on holidays.
"""
from __future__ import annotations
import json
from dk.config import load_watchlist
from dk.util import session
from dk.sources import premarket, market_movers
from dk.store import db as store


def _cfg() -> dict:
    return load_watchlist().get("premarket") or {}


def _watchlist_symbols() -> list[str]:
    wl = load_watchlist()
    syms: list[str] = []
    for grp in ("equities", "etfs"):
        for item in (wl.get(grp) or []):
            s = item.get("symbol") if isinstance(item, dict) else item
            if s:
                syms.append(s)
    return syms


def run_once(push: bool = True, force: bool = False) -> dict:
    """One pre-market scan tick. force=True bypasses the session gate (testing)."""
    cfg = _cfg()
    if not cfg.get("enabled", True):
        return {"skipped": "disabled"}
    if not force and not session.is_premarket_window():
        return {"skipped": "not premarket", "phase": session.session_phase()}

    watch = _watchlist_symbols()
    movers: list[str] = []
    if cfg.get("include_movers", True):
        try:
            movers = [m["symbol"] for m in market_movers.fetch_movers() if m.get("symbol")]
        except Exception as e:
            print(f"[premarket_scan] movers fetch failed: {e}")

    gappers, health = premarket.scan_gaps(
        watch, movers,
        watchlist_min_pct=float(cfg.get("watchlist_min_pct", 2.0)),
        movers_min_pct=float(cfg.get("movers_min_pct", 4.0)),
        max_movers=int(cfg.get("max_movers", 30)),
    )
    if not gappers:
        out = {"scanned": True, "gappers": 0, "phase": session.session_phase()}
        if health.get("degraded"):  # outage, not a quiet tape — make it visible
            out["feed"] = "degraded"
            out["failed"] = f"{health['failed']}/{health['total']}"
            print(f"[premarket_scan] feed degraded — {out['failed']} symbols "
                  "returned no data (possible Yahoo IP block)")
        return out

    cooldown = int(cfg.get("cooldown_minutes", 90))
    top_n = int(cfg.get("max_alerts", 6))
    store.init_db()
    new_alerts = 0
    fired: list[str] = []
    with store.conn() as c:
        for g in gappers[:top_n]:
            sym = g["symbol"]
            recent = c.execute(
                "SELECT 1 FROM alerts WHERE symbol=? AND kind='PREMARKET_GAP' "
                "AND created_at >= datetime('now', ?) LIMIT 1",
                (sym, f"-{cooldown} minutes"),
            ).fetchone()
            if recent:
                continue
            arrow = "🟢" if g["gap_pct"] > 0 else "🔴"
            star = "⭐" if g["on_watchlist"] else ""
            msg = (f"{arrow} PRE-MKT {sym}{star} {g['gap_pct']:+.1f}% "
                   f"(${g['premarket']:g} vs ${g['prev_close']:g} prior close)")
            c.execute(
                "INSERT INTO alerts (symbol, kind, message, payload) VALUES (?,?,?,?)",
                (sym, "PREMARKET_GAP", msg, json.dumps(g)),
            )
            new_alerts += 1
            fired.append(f"{sym} {g['gap_pct']:+.1f}%")

    summary = {"scanned": True, "gappers": len(gappers), "alerts": new_alerts, "fired": fired}
    if push and new_alerts:
        try:
            from dk.notify import sms
            summary["push"] = sms.push_digest()
        except Exception as e:
            print(f"[premarket_scan] push failed: {e}")
            summary["push"] = {"error": str(e)}
    return summary


if __name__ == "__main__":
    print(run_once(push=False, force=True))
