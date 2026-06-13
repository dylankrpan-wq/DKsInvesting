"""Follow-the-trade tracker for pushed perp setups.

Each auto-pushed SETUP_SCAN setup (entry/stop/TP1/TP2/TP3) is registered as an
open signal. check() runs frequently (in the fast spike loop): it pulls live
prices and pings the phone the moment a setup touches a TP rung or its stop,
laddering TP1 -> TP2 -> TP3 and closing on stop or TP3. hourly_recap() sends a
consolidated "how the open setups are doing" summary each hour.

Reports what price actually did vs the setup's own levels — not advice. Uses
`last` per check, so very fast intra-check wicks can be missed (documented).
"""
from __future__ import annotations
import sqlite3
from datetime import datetime, timezone
from dk.config import load_watchlist
from dk.store import db as store

_TP_COLS = ("tp1", "tp2", "tp3")


def _cfg() -> dict:
    return (load_watchlist().get("perp_tracker") or {})


def _fmt(p):
    from dk.analysis.perp import _fmt as f
    return f(p)


def _gain_pct(side: str, entry: float, price: float) -> float:
    if not entry:
        return 0.0
    return ((price - entry) if side == "long" else (entry - price)) / entry * 100.0


def register_signal(source_alert_id: int, row: dict) -> bool:
    """Register a pushed setup as an open tracked signal. row is the scanner row
    (inst_id, side, entry, stop, tps). Skips if disabled or already open/dup."""
    if not _cfg().get("enabled", True):
        return False
    tps = row.get("tps") or []
    levels = [tp.get("level") for tp in tps] + [None, None, None]
    with store.conn() as c:
        dup = c.execute(
            """SELECT 1 FROM perp_signals WHERE inst_id=? AND side=? AND status='open'
               LIMIT 1""", (row["inst_id"], row["side"])).fetchone()
        if dup:
            return False
        try:
            c.execute(
                """INSERT INTO perp_signals
                   (source_alert_id, inst_id, side, entry, stop, tp1, tp2, tp3, last_price)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (source_alert_id, row["inst_id"], row["side"], row["entry"], row["stop"],
                 levels[0], levels[1], levels[2], row["entry"]))
        except sqlite3.IntegrityError:
            return False  # this alert already registered
    return True


def _open_signals(c) -> list[sqlite3.Row]:
    return c.execute("SELECT * FROM perp_signals WHERE status='open'").fetchall()


def check(price_map: dict | None = None, push: bool = True) -> dict:
    """Detect TP/stop touches on open signals; ping on each event. price_map:
    {inst_id: last}. Fetches all perp tickers if not supplied."""
    if not _cfg().get("enabled", True):
        return {"skipped": "disabled"}
    store.init_db()
    with store.conn() as c:
        signals = _open_signals(c)
        if not signals:
            return {"open": 0, "events": 0}

        if price_map is None:
            from dk.sources import crypto_deriv
            price_map = {t["inst_id"]: t["last"] for t in crypto_deriv.fetch_tickers("SWAP")}
        if not price_map:
            return {"open": len(signals), "events": 0, "note": "no price data"}

        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        msgs: list[str] = []
        events = 0
        for s in signals:
            last = price_map.get(s["inst_id"])
            if not last:
                continue
            side, entry = s["side"], s["entry"]
            gain = _gain_pct(side, entry, last)
            mfe = max(s["mfe_pct"] or 0, gain)
            mae = min(s["mae_pct"] or 0, gain)
            hit = set(filter(None, (s["tp_hits"] or "").split(",")))
            new_hits = []
            for col in _TP_COLS:
                lvl = s[col]
                if lvl and col not in hit:
                    reached = last >= lvl if side == "long" else last <= lvl
                    if reached:
                        hit.add(col); new_hits.append((col, lvl))
            stopped = (last <= s["stop"]) if side == "long" else (last >= s["stop"])

            arrow = "🟢" if side == "long" else "🔴"
            tag = f"{arrow} {s['inst_id']} {side}"
            status = "open"
            resolved = None
            if stopped:
                status = "stopped"; resolved = now
                prior = (" after " + "/".join(sorted(hit)).upper()) if hit else ""
                msgs.append(f"🛑 {tag} STOPPED at ${_fmt(last)} ({gain:+.1f}%{prior}). "
                            f"Closed. (MFE {mfe:+.1f}%)")
                events += 1
            else:
                for col, lvl in new_hits:
                    events += 1
                    if col == "tp3":
                        status = "tp3"; resolved = now
                        msgs.append(f"✅ {tag} hit TP3 ${_fmt(lvl)} ({gain:+.1f}%) — "
                                    f"full target. Closed.")
                    else:
                        nxt = "tp2" if col == "tp1" else "tp3"
                        nxt_lvl = s[nxt]
                        msgs.append(f"🎯 {tag} hit {col.upper()} ${_fmt(lvl)} ({gain:+.1f}%). "
                                    f"Next {nxt.upper()} ${_fmt(nxt_lvl)}, stop ${_fmt(s['stop'])}. "
                                    f"(open)")

            c.execute(
                """UPDATE perp_signals SET tp_hits=?, status=?, mfe_pct=?, mae_pct=?,
                   last_price=?, resolved_at=COALESCE(?, resolved_at) WHERE id=?""",
                (",".join(sorted(hit)), status, round(mfe, 2), round(mae, 2),
                 last, resolved, s["id"]))
            # Record events in the alerts table for dashboard/history
            for m in (msgs[-len(new_hits) - (1 if stopped else 0):] if (new_hits or stopped) else []):
                c.execute("INSERT INTO alerts (symbol, kind, message) VALUES (?,?,?)",
                          (s["inst_id"], "PERP_TRACK", m))

    summary = {"open": len(signals), "events": events}
    if push and msgs:
        from dk.notify import sms
        body = "📊 Perp setup update:\n\n" + "\n".join(msgs)
        try:
            summary["chunks"] = sms.send_summary(body)
        except Exception as e:
            print(f"[perp_tracker] send failed: {e}")
            summary["error"] = str(e)
    return summary


def hourly_recap(push: bool = True) -> dict:
    """Consolidated 'how the open setups are doing' summary; no-op if none open."""
    if not _cfg().get("enabled", True) or not _cfg().get("hourly_recap", True):
        return {"skipped": "disabled"}
    store.init_db()
    with store.conn() as c:
        signals = _open_signals(c)
        if not signals:
            return {"open": 0}
        from dk.sources import crypto_deriv
        price_map = {t["inst_id"]: t["last"] for t in crypto_deriv.fetch_tickers("SWAP")}
        lines = []
        for s in signals:
            last = price_map.get(s["inst_id"])
            if not last:
                continue
            gain = _gain_pct(s["side"], s["entry"], last)
            hit = set(filter(None, (s["tp_hits"] or "").split(",")))
            rungs = " ".join((col.upper() + ("✓" if col in hit else "·")) for col in _TP_COLS)
            arrow = "🟢" if s["side"] == "long" else "🔴"
            lines.append(f"{arrow} {s['inst_id']} {s['side']}: {gain:+.1f}% "
                         f"[{rungs}] MFE {s['mfe_pct']:+.1f}% · stop ${_fmt(s['stop'])}")
    if not lines:
        return {"open": len(signals), "note": "no prices"}
    summary = {"open": len(lines)}
    if push:
        from dk.notify import sms
        body = f"📈 Open perp setups — how they're doing ({len(lines)}):\n\n" + "\n".join(lines)
        try:
            summary["chunks"] = sms.send_summary(body)
        except Exception as e:
            print(f"[perp_tracker] recap send failed: {e}")
            summary["error"] = str(e)
    return summary


if __name__ == "__main__":
    import io
    import sys
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    print("check:", check(push=False))
    print("recap:", hourly_recap(push=False))
