"""Daily performance recap — how the hypothetical call-outs/ideas are doing.

Once a day (after the US close), pushes ONE Telegram summary of both track
records: the perp call-out scorecard and the equity idea scorecard — W/L,
win-rate, expectancy, total R, what resolved today, and (equities) the by-horizon
split. The honest daily scoreboard for the track-and-learn loop. Discovery, not
advice. Poller-driven + ET-gated + idempotent (perf_recaps table), so it sends
exactly once per day regardless of restarts.
"""
from __future__ import annotations
from datetime import datetime, timezone
from dk.config import load_watchlist
from dk.util import session
from dk.store import db as store


def _cfg() -> dict:
    return (load_watchlist().get("perf_recap") or {})


def _today_utc() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _closed_today(rows: list[dict], sym_key: str) -> list[str]:
    """One-liners for call-outs/ideas that resolved (WIN/LOSS) in today's build."""
    today = _today_utc()
    out = []
    for r in rows:
        ra = str(r.get("resolved_at") or "")[:10]
        if ra == today and r.get("status") in ("WIN", "LOSS"):
            icon = "✅" if r["status"] == "WIN" else "🛑"
            rr = f"{r['realized_r']:+}R" if r.get("realized_r") is not None else ""
            out.append(f"  {icon} {r.get(sym_key)} {r['status']} {rr}")
    return out[:6]


def _perp_block() -> str | None:
    try:
        from dk.analysis import perp_scorecard as sc
        rows = sc.build_ledger()
    except Exception as e:
        print(f"[perf_recap] perp scorecard failed: {e}")
        return None
    if not rows:
        return None
    s = sc.summary(rows)
    wr = f"{s['win_rate_pct']}%" if s["win_rate_pct"] is not None else "—"
    exp = f"{s['expectancy_r']:+}R" if s["expectancy_r"] is not None else "—"
    L = [f"🪙 Perps — {s['total']} call-outs ({s.get('pushed', 0)}p/{s.get('tracked', 0)}t) · "
         f"{s['wins']}W/{s['losses']}L/{s['open']} open · win {wr} · exp {exp} · "
         f"total {s['total_r']:+}R"]
    L += _closed_today(rows, "inst_id")
    return "\n".join(L)


def _equity_block() -> str | None:
    try:
        from dk.analysis import equity_scorecard as sc
        rows = sc.build_ledger(max_refresh=int(_cfg().get("equity_refresh", 20)))
    except Exception as e:
        print(f"[perf_recap] equity scorecard failed: {e}")
        return None
    if not rows:
        return None
    s = sc.summary(rows)
    wr = f"{s['win_rate_pct']}%" if s["win_rate_pct"] is not None else "—"
    exp = f"{s['expectancy_r']:+}R" if s["expectancy_r"] is not None else "—"
    L = [f"💡 Equities — {s['total']} ideas ({s['pushed']}p/{s['tracked']}t) · "
         f"{s['wins']}W/{s['losses']}L/{s['open']} open · win {wr} · exp {exp} · "
         f"total {s['total_r']:+}R"]
    # compact by-horizon total-R line (resolved only)
    res = [r for r in rows if r.get("status") in ("WIN", "LOSS", "EXPIRED")]
    bits = []
    for hz, lbl in (("short_term", "ST"), ("swing", "SW"), ("long_term", "LT")):
        g = [r for r in res if r.get("horizon") == hz]
        rr = [r["realized_r"] for r in g if r.get("realized_r") is not None]
        if g:
            bits.append(f"{lbl} {round(sum(rr), 1):+}R ({len(g)})")
    if bits:
        L.append("  by horizon: " + " · ".join(bits))
    L += _closed_today(rows, "symbol")
    return "\n".join(L)


def build_text() -> str:
    et = session.now_et()
    parts = [f"📊 DK daily performance — {et:%a %b %d}",
             "How the hypothetical call-outs are doing (track-and-learn).", ""]
    pb = _perp_block()
    eb = _equity_block()
    if pb:
        parts.append(pb)
    if eb:
        parts.append("")
        parts.append(eb)
    if not pb and not eb:
        parts.append("No tracked call-outs resolved yet — they'll build as the scanners fire.")
    parts.append("")
    parts.append("Discovery, not advice — measured from candles, win-rate is low by design "
                 "(small losers, big winners); judge by expectancy/total R.")
    return "\n".join(parts)


def maybe_send(force: bool = False) -> dict:
    """Poller gate: send once per ET day, after the configured hour. Idempotent."""
    cfg = _cfg()
    if not cfg.get("enabled", True):
        return {"skipped": "disabled"}
    from dk.notify import sms
    if not sms.is_configured():
        return {"skipped": "no phone channel"}

    store.init_db()
    today = session.now_et().date().isoformat()
    if not force:
        et = session.now_et()
        start = et.replace(hour=int(cfg.get("hour_et", 17)),
                           minute=int(cfg.get("minute", 0)), second=0, microsecond=0)
        if et < start:
            return {"skipped": f"before the {start:%H:%M} ET recap time"}
        with store.conn() as c:
            if c.execute("SELECT 1 FROM perf_recaps WHERE recap_date=?", (today,)).fetchone():
                return {"skipped": f"recap for {today} already sent"}

    text = build_text()
    sent = sms.send_summary(text)
    if sent:  # record only after a successful send, so a failure retries next poll
        with store.conn() as c:
            c.execute("INSERT OR IGNORE INTO perf_recaps (recap_date) VALUES (?)", (today,))
    return {"sent": sent, "recap_date": today,
            "at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")}


if __name__ == "__main__":
    import io
    import sys
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    print(build_text())
