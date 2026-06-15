"""Overnight 'while you slept' digest — a template (no-LLM) pre-wake summary.

Poller-driven (like the desk/morning briefs): on trading-day mornings, the first
poll inside the ET window (default 06:30-09:30 ET) sends ONE digest — US index
futures + overseas index moves (live, keyless) plus the top breaking overnight
headlines — then records it in overnight_digests so it never double-sends (across
restarts or a second scheduler instance). ET-gated so it's DST-correct without
relying on APScheduler timezone handling. The Claude-written morning brief
(dk/briefing/morning_brief) comes later, closer to the open.
"""
from __future__ import annotations
import sqlite3
from datetime import datetime, timedelta, timezone
from dk.config import DB_PATH, load_watchlist
from dk.util import session
from dk.sources import overnight_markets
from dk.store import db as store


def _cfg() -> dict:
    return (load_watchlist().get("overnight") or {})


def _overnight_headlines(hours: int = 14, limit: int = 8) -> list[dict]:
    """Breaking-first headlines from the trailing overnight window."""
    try:
        with sqlite3.connect(DB_PATH) as c:
            c.row_factory = sqlite3.Row
            rows = c.execute(
                f"""SELECT symbol, source, title, is_breaking, fetched_at
                    FROM news
                    WHERE fetched_at >= datetime('now', '-{int(hours)} hours')
                      AND title IS NOT NULL
                    ORDER BY is_breaking DESC, fetched_at DESC
                    LIMIT {int(limit)}""").fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        print(f"[overnight] headline query failed: {e}")
        return []


def build_text() -> str:
    """Assemble the overnight digest message."""
    et = session.now_et()
    lines = [f"🌙 Overnight recap — {et:%a %b %d, %H:%M} ET", ""]

    markets = overnight_markets.fetch()
    mkt = overnight_markets.format_line(markets)
    if mkt:
        lines.append(mkt)
    elif not markets.get("futures") and not markets.get("overseas"):
        # Both groups empty = a fetch outage, not a flat tape (futures/overseas
        # trade ~24h). Say so rather than silently omitting the line.
        lines.append("⚠️ Overnight index feed unavailable (futures/overseas not fetched)")

    heads = _overnight_headlines(
        hours=int(_cfg().get("headline_hours", 14)),
        limit=int(_cfg().get("max_headlines", 8)))
    if heads:
        lines.append("")
        lines.append("📰 Overnight headlines:")
        for h in heads:
            tag = "⚡ " if h.get("is_breaking") else "• "
            sym = f"[{h['symbol']}] " if h.get("symbol") else ""
            src = f" — {h['source']}" if h.get("source") else ""
            title = (h.get("title") or "").strip()[:160]
            lines.append(f"{tag}{sym}{title}{src}")

    lines.append("")
    lines.append("Pre-market gappers will ping as they form; full morning brief before the open.")
    return "\n".join(lines)


def maybe_send(force: bool = False) -> dict:
    """Poller gate. Sends once on a trading-day morning inside the ET window,
    idempotent via the overnight_digests table. Cheap no-op otherwise."""
    cfg = _cfg()
    if not cfg.get("enabled", True):
        return {"skipped": "disabled"}
    if not force and not session.is_trading_day():
        return {"skipped": "not a trading day"}

    if not force:
        et = session.now_et()
        start = et.replace(hour=int(cfg.get("hour_et", 6)),
                           minute=int(cfg.get("minute", 30)),
                           second=0, microsecond=0)
        if et < start:
            return {"skipped": f"before the {start:%H:%M} ET overnight window"}
        if et - start > timedelta(hours=float(cfg.get("window_hours", 3.0))):
            return {"skipped": "past the overnight window for today"}

    from dk.notify import sms
    if not sms.is_configured():
        return {"skipped": "no phone channel configured"}

    store.init_db()
    today = session.now_et().date().isoformat()
    if not force:
        with store.conn() as c:
            if c.execute("SELECT 1 FROM overnight_digests WHERE digest_date=?",
                         (today,)).fetchone():
                return {"skipped": f"overnight digest for {today} already sent"}

    text = build_text()
    sent = sms.send_summary(text)
    if sent:  # record only after a successful send, so a failure retries next poll
        with store.conn() as c:
            c.execute("INSERT OR IGNORE INTO overnight_digests (digest_date, chunks) "
                      "VALUES (?, ?)", (today, sent))
    return {"sent": sent, "channel": sms.active_channel(), "digest_date": today,
            "at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")}


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    except Exception:
        pass
    print(build_text())
