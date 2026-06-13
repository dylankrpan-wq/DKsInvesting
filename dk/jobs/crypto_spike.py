"""Fast crypto-derivatives spike detector.

Runs on a sub-minute timer (separate from the 15-min poll). Each tick:
  1. snapshot all Blofin perp tickers
  2. compare each pair's price to its price N minutes ago (rolling history)
  3. emit a CRYPTO_SPIKE alert when |move| crosses a window threshold
     (e.g. +6% in 3 min, +12% in 10 min), with a per-symbol cooldown
  4. push the phone immediately (the whole point is speed)

Catches the BEAT-USDT / TRUMP-USDT style short-window pumps the 24h
CRYPTO_MOVE alert is too slow and too coarse to see.
"""
from __future__ import annotations
import json
from datetime import datetime, timedelta, timezone
from dk.config import load_watchlist
from dk.sources import crypto_deriv
from dk.store import db as store

# Defaults (overridable in config/watchlist.yaml -> crypto_spike)
_DEFAULT_WINDOWS = [{"minutes": 3, "pct": 6.0}, {"minutes": 10, "pct": 12.0}]
_DEFAULT_RETENTION_MIN = 15
_DEFAULT_MIN_VOL_USD = 100_000.0
_DEFAULT_COOLDOWN_MIN = 30
_DEFAULT_DIRECTION = "both"   # 'up' | 'down' | 'both'


def _cfg() -> dict:
    return (load_watchlist().get("crypto_spike") or {})


def interval_seconds() -> int:
    return int(_cfg().get("interval_seconds", 90))


def _fmt_price(p: float) -> str:
    """Readable price across magnitudes — meme perps are sub-cent, so avoid the
    scientific notation a plain '%g' would produce."""
    if p >= 1000:
        return f"{p:,.2f}"
    if p >= 1:
        return f"{p:,.4f}".rstrip("0").rstrip(".")
    return f"{p:.8f}".rstrip("0").rstrip(".")  # sub-$1: fixed, trimmed


def run_once(push: bool = True) -> dict:
    """One fast tick. Returns a summary dict; pushes the phone if new alerts."""
    cfg = _cfg()
    if not cfg.get("enabled", True):
        return {"skipped": "disabled"}

    inst_type = cfg.get("inst_type", "SWAP")
    windows = cfg.get("windows") or _DEFAULT_WINDOWS
    min_vol = float(cfg.get("min_quote_vol_usd", _DEFAULT_MIN_VOL_USD))
    cooldown = int(cfg.get("cooldown_minutes", _DEFAULT_COOLDOWN_MIN))
    direction = (cfg.get("direction") or _DEFAULT_DIRECTION).lower()

    # A baseline must be at least `wmin` old but no more than `wmin + slack` old,
    # so a scheduler gap (laptop sleep, outage) can't compare today's price to a
    # badly-stale tick and fire a false "fast move". slack scales with cadence.
    interval = int(cfg.get("interval_seconds", 90))
    slack_s = max(2 * interval, 60)
    max_window = max((int(w["minutes"]) for w in windows), default=10)
    # Keep enough history that the largest window's baseline isn't pruned away.
    retention = max(int(cfg.get("retention_minutes", _DEFAULT_RETENTION_MIN)),
                    max_window + (slack_s // 60) + 1)

    tickers = crypto_deriv.fetch_tickers(inst_type)
    if not tickers:
        return {"fetched": 0, "alerts": 0, "note": "no ticker data"}

    now = datetime.now(timezone.utc)
    now_iso = now.isoformat(timespec="seconds")
    price_now = {t["inst_id"]: t for t in tickers if t.get("inst_id")}

    store.init_db()
    new_alerts = 0
    fired: list[str] = []

    with store.conn() as c:
        for inst_id, t in price_now.items():
            if t["quote_vol_usd"] < min_vol:
                continue
            best = None  # (pct, window_min, then_price)
            for w in windows:
                wmin = int(w["minutes"])
                thr = float(w["pct"])
                upper = (now - timedelta(minutes=wmin)).isoformat(timespec="seconds")
                lower = (now - timedelta(minutes=wmin, seconds=slack_s)).isoformat(timespec="seconds")
                row = c.execute(
                    """SELECT last FROM crypto_deriv_ticks
                       WHERE inst_id=? AND ts <= ? AND ts >= ?
                       ORDER BY ts DESC LIMIT 1""",
                    (inst_id, upper, lower),
                ).fetchone()
                if not row or not row[0]:
                    continue
                then_price = row[0]
                pct = (t["last"] - then_price) / then_price * 100.0
                if direction == "up" and pct < 0:
                    continue
                if direction == "down" and pct > 0:
                    continue
                if abs(pct) < thr:
                    continue
                # Prefer the most extreme move across windows
                if best is None or abs(pct) > abs(best[0]):
                    best = (pct, wmin, then_price)

            if best is None:
                continue

            # Per-pair cooldown — keyed on the full inst_id so BTC-USDT and
            # BTC-USDC are tracked independently (don't suppress each other).
            recent = c.execute(
                """SELECT 1 FROM alerts WHERE symbol=? AND kind='CRYPTO_SPIKE'
                   AND created_at >= datetime('now', ?) LIMIT 1""",
                (inst_id, f"-{cooldown} minutes"),
            ).fetchone()
            if recent:
                continue

            pct, wmin, then_price = best
            arrow = "🟢 PUMP" if pct > 0 else "🔴 DUMP"
            chg24 = t.get("chg_24h_pct")
            chg24_s = f", {chg24:+.1f}% 24h" if chg24 is not None else ""
            msg = (f"{arrow} {inst_id} {pct:+.1f}% in {wmin}m "
                   f"(now ${_fmt_price(t['last'])}{chg24_s}) — fast derivatives move")
            c.execute(
                "INSERT INTO alerts (symbol, kind, message, payload) VALUES (?,?,?,?)",
                (inst_id, "CRYPTO_SPIKE", msg,
                 json.dumps({"inst_id": inst_id, "pct": round(pct, 2),
                             "window_min": wmin, "price": t["last"],
                             "chg_24h_pct": chg24,
                             "quote_vol_usd": round(t["quote_vol_usd"])})),
            )
            new_alerts += 1
            fired.append(f"{inst_id} {pct:+.1f}%/{wmin}m")

        # Record this tick's prices, then prune history beyond retention.
        # Prune cutoff is computed in Python so it matches our stored isoformat
        # ts exactly — SQLite's datetime('now') uses a space (not 'T') and no
        # offset, which would sort wrong against isoformat and never prune.
        c.executemany(
            "INSERT OR REPLACE INTO crypto_deriv_ticks (inst_id, ts, last) VALUES (?,?,?)",
            [(iid, now_iso, t["last"]) for iid, t in price_now.items()],
        )
        prune_cutoff = (now - timedelta(minutes=retention)).isoformat(timespec="seconds")
        c.execute("DELETE FROM crypto_deriv_ticks WHERE ts < ?", (prune_cutoff,))

    summary = {"fetched": len(price_now), "alerts": new_alerts, "fired": fired}

    if push and new_alerts:
        try:
            from dk.notify import sms
            summary["push"] = sms.push_digest()
        except Exception as e:
            print(f"[crypto_spike] push failed: {e}")
            summary["push"] = {"error": str(e)}
    return summary


if __name__ == "__main__":
    print(run_once(push=False))
