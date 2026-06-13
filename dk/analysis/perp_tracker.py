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


def _prices(price_map: dict | None) -> dict | None:
    if price_map is not None:
        return price_map
    from dk.sources import crypto_deriv
    return {t["inst_id"]: t["last"] for t in crypto_deriv.fetch_tickers("SWAP")}


def check(price_map: dict | None = None, push: bool = True) -> dict:
    """Detect TP/stop touches on open signals and ping on each event. Prices are
    fetched OUTSIDE any DB transaction; events are SENT before the hit/status
    change is persisted, so a failed send isn't silently lost (it retries next
    tick). price_map {inst_id: last} is reused from the spike loop when passed."""
    cfg = _cfg()
    if not cfg.get("enabled", True):
        return {"skipped": "disabled"}
    store.init_db()
    max_age_h = int(cfg.get("max_age_hours", 48))

    # 1) Expire stale open signals, then read the open set (short write conn)
    with store.conn() as c:
        c.execute("""UPDATE perp_signals SET status='expired', resolved_at=datetime('now')
                     WHERE status='open' AND opened_at < datetime('now', ?)""",
                  (f"-{max_age_h} hours",))
        signals = _open_signals(c)
    if not signals:
        return {"open": 0, "events": 0}

    # 2) Prices outside any connection — never hold the writer across the network
    price_map = _prices(price_map)
    if not price_map:
        return {"open": len(signals), "events": 0, "note": "no price data"}

    # 3) Detect in memory; each signal carries its OWN message list
    updates = []
    all_msgs: list[str] = []
    for s in signals:
        last = price_map.get(s["inst_id"])
        if not last:
            continue
        side, entry = s["side"], s["entry"]
        gain = _gain_pct(side, entry, last)
        mfe = round(max(s["mfe_pct"] or 0, gain), 2)
        mae = round(min(s["mae_pct"] or 0, gain), 2)
        hit = set(filter(None, (s["tp_hits"] or "").split(",")))
        new_hits = []
        for col in _TP_COLS:
            lvl = s[col]
            if lvl and col not in hit:
                if (last >= lvl) if side == "long" else (last <= lvl):
                    hit.add(col); new_hits.append((col, lvl))
        stopped = (last <= s["stop"]) if side == "long" else (last >= s["stop"])
        arrow = "🟢" if side == "long" else "🔴"
        tag = f"{arrow} {s['inst_id']} {side}"
        status, resolved, smsgs = "open", False, []
        if stopped:
            prior = (" after " + "/".join(sorted(hit)).upper()) if hit else ""
            smsgs.append(f"🛑 {tag} STOPPED at ${_fmt(last)} ({gain:+.1f}%{prior}). "
                         f"Closed. (MFE {mfe:+.1f}%)")
            status, resolved = "stopped", True
        else:
            for col, lvl in new_hits:
                if col == "tp3":
                    smsgs.append(f"✅ {tag} hit TP3 ${_fmt(lvl)} ({gain:+.1f}%) — "
                                 f"full target. Closed.")
                    status, resolved = "tp3", True
                else:
                    nxt = "tp2" if col == "tp1" else "tp3"
                    smsgs.append(f"🎯 {tag} hit {col.upper()} ${_fmt(lvl)} ({gain:+.1f}%). "
                                 f"Next {nxt.upper()} ${_fmt(s[nxt])}, stop ${_fmt(s['stop'])}. (open)")
        updates.append({"id": s["id"], "inst": s["inst_id"], "hits": ",".join(sorted(hit)),
                        "status": status, "resolved": resolved, "mfe": mfe, "mae": mae,
                        "last": last, "msgs": smsgs})
        all_msgs.extend(smsgs)

    # 4) Send FIRST — a failed send must not mark the events as seen
    sent_ok = True
    if push and all_msgs:
        from dk.notify import sms
        body = "📊 Perp setup update:\n\n" + "\n".join(all_msgs)
        try:
            sent_ok = sms.send_summary(body) > 0
        except Exception as e:
            print(f"[perp_tracker] send failed: {e}")
            sent_ok = False

    # 5) Persist: always price/MFE/MAE; commit hit/status only if the ping went out
    events = 0
    with store.conn() as c:
        for u in updates:
            if u["msgs"] and not sent_ok:
                c.execute("UPDATE perp_signals SET mfe_pct=?, mae_pct=?, last_price=? WHERE id=?",
                          (u["mfe"], u["mae"], u["last"], u["id"]))
                continue
            if u["resolved"]:
                c.execute("""UPDATE perp_signals SET tp_hits=?, status=?, mfe_pct=?, mae_pct=?,
                             last_price=?, resolved_at=datetime('now') WHERE id=?""",
                          (u["hits"], u["status"], u["mfe"], u["mae"], u["last"], u["id"]))
            else:
                c.execute("""UPDATE perp_signals SET tp_hits=?, status=?, mfe_pct=?, mae_pct=?,
                             last_price=? WHERE id=?""",
                          (u["hits"], u["status"], u["mfe"], u["mae"], u["last"], u["id"]))
            for m in u["msgs"]:
                events += 1
                c.execute("INSERT INTO alerts (symbol, kind, message) VALUES (?,?,?)",
                          (u["inst"], "PERP_TRACK", m))
    return {"open": len(signals), "events": events,
            "sent": (sent_ok if all_msgs else None)}


def hourly_recap(push: bool = True) -> dict:
    """Consolidated 'how the open setups are doing' summary; no-op if none open."""
    cfg = _cfg()
    if not cfg.get("enabled", True) or not cfg.get("hourly_recap", True):
        return {"skipped": "disabled"}
    store.init_db()
    with store.conn() as c:
        signals = c.execute(
            "SELECT * FROM perp_signals WHERE status='open' ORDER BY opened_at DESC").fetchall()
    if not signals:
        return {"open": 0}
    price_map = _prices(None)  # fetched outside the conn
    cap = int(cfg.get("recap_max", 12))
    lines = []
    for s in signals[:cap]:
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
    extra = len(signals) - len(lines)
    summary = {"open": len(signals)}
    if push:
        from dk.notify import sms
        body = (f"📈 Open perp setups — how they're doing ({len(signals)}):\n\n"
                + "\n".join(lines) + (f"\n…+{extra} more" if extra > 0 else ""))
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
