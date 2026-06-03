"""Alert engine — runs after each poll cycle.

Detects:
  - PRICE_MOVE: latest close moves >= price_move_pct vs prior close
  - VOLUME_SPIKE: latest volume >= volume_spike_x * 20-day avg volume
  - EARNINGS_NEAR: report_date within earnings_window_days
  - SENTIMENT_SURGE: avg sentiment over last N articles for ticker exceeds threshold
  - CRYPTO_MOVE: 24h change exceeds price_move_pct

Inserts rows into `alerts` table; deduped per (symbol, kind, day).
"""
from __future__ import annotations
import json
import sqlite3
from datetime import date, datetime, timedelta, timezone
from dk.config import DB_PATH, load_watchlist


def _already_alerted_today(c, symbol: str, kind: str) -> bool:
    today = date.today().isoformat()
    row = c.execute(
        "SELECT 1 FROM alerts WHERE symbol=? AND kind=? AND substr(created_at,1,10)=? LIMIT 1",
        (symbol, kind, today),
    ).fetchone()
    return row is not None


def _emit(c, symbol: str, kind: str, message: str, payload: dict) -> int:
    if _already_alerted_today(c, symbol, kind):
        return 0
    c.execute(
        "INSERT INTO alerts (symbol, kind, message, payload) VALUES (?, ?, ?, ?)",
        (symbol, kind, message, json.dumps(payload)),
    )
    return 1


def _check_prices(c, cfg: dict) -> int:
    move_pct = float(cfg.get("price_move_pct", 5.0))
    spike_x = float(cfg.get("volume_spike_x", 3.0))
    n = 0
    syms = [r[0] for r in c.execute("SELECT DISTINCT symbol FROM prices").fetchall()]
    for sym in syms:
        rows = c.execute(
            "SELECT ts, close, volume FROM prices WHERE symbol=? ORDER BY ts DESC LIMIT 21",
            (sym,),
        ).fetchall()
        if len(rows) < 2:
            continue
        latest_close, latest_vol = rows[0][1], rows[0][2]
        prior_close = rows[1][1]
        if latest_close and prior_close:
            pct = (latest_close - prior_close) / prior_close * 100.0
            if abs(pct) >= move_pct:
                direction = "up" if pct > 0 else "down"
                n += _emit(c, sym, "PRICE_MOVE",
                           f"{sym} {direction} {pct:+.2f}% (close {latest_close:.2f})",
                           {"pct": pct, "close": latest_close, "prior_close": prior_close})
        # Volume spike vs trailing 20-day avg (excluding latest)
        vols = [r[2] for r in rows[1:] if r[2]]
        if latest_vol and len(vols) >= 5:
            avg = sum(vols) / len(vols)
            if avg > 0 and latest_vol >= spike_x * avg:
                n += _emit(c, sym, "VOLUME_SPIKE",
                           f"{sym} volume {latest_vol/avg:.1f}x its {len(vols)}-day avg",
                           {"latest": latest_vol, "avg": avg, "x": latest_vol / avg})
    return n


def _check_earnings(c, cfg: dict) -> int:
    window = int(cfg.get("earnings_window_days", 7))
    today = date.today()
    horizon = today + timedelta(days=window)
    n = 0
    rows = c.execute(
        "SELECT symbol, report_date FROM earnings WHERE report_date BETWEEN ? AND ?",
        (today.isoformat(), horizon.isoformat()),
    ).fetchall()
    for sym, rd in rows:
        try:
            d = datetime.fromisoformat(rd).date() if "T" in rd else date.fromisoformat(rd[:10])
        except Exception:
            continue
        days = (d - today).days
        n += _emit(c, sym, "EARNINGS_NEAR",
                   f"{sym} reports earnings in {days} day{'s' if days != 1 else ''} ({rd[:10]})",
                   {"report_date": rd, "days_out": days})
    return n


def _check_sentiment_surge(c, cfg: dict) -> int:
    thresh = float(cfg.get("sentiment_threshold", 0.6))
    min_articles = int(cfg.get("sentiment_min_articles", 3))
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    n = 0
    rows = c.execute(
        """SELECT symbol, AVG(sentiment) AS avg_s, COUNT(*) AS cnt
           FROM news
           WHERE symbol IS NOT NULL AND sentiment IS NOT NULL AND fetched_at >= ?
           GROUP BY symbol
           HAVING cnt >= ? AND ABS(avg_s) >= ?""",
        (cutoff, min_articles, thresh),
    ).fetchall()
    for sym, avg_s, cnt in rows:
        tone = "bullish" if avg_s > 0 else "bearish"
        n += _emit(c, sym, "SENTIMENT_SURGE",
                   f"{sym} {tone} sentiment {avg_s:+.2f} across {cnt} recent articles",
                   {"avg": avg_s, "count": cnt, "window_h": 24})
    return n


def _check_macro(c, cfg: dict) -> int:
    window = int(cfg.get("macro_window_days", 3))
    n = 0
    rows = c.execute(
        """SELECT id, event_date, category, title, importance FROM macro_events
           WHERE importance >= 2
             AND event_date BETWEEN date('now') AND date('now', ?)""",
        (f"+{window} days",),
    ).fetchall()
    for ev_id, ev_date, cat, title, imp in rows:
        # Use event id as the "symbol" for dedup so each event alerts at most once.
        if _already_alerted_today(c, ev_id, "MACRO_NEAR"):
            continue
        c.execute(
            "INSERT INTO alerts (symbol, kind, message, payload) VALUES (?, ?, ?, ?)",
            (ev_id, "MACRO_NEAR",
             f"{cat}: {title} on {ev_date}",
             json.dumps({"event_date": ev_date, "category": cat, "importance": imp})),
        )
        n += 1
    return n


def _check_breaking_news(c, cfg: dict) -> int:
    """Surface high-impact breaking news as alerts. Dedupes per article (id)."""
    n = 0
    rows = c.execute(
        """SELECT id, symbol, source, title, url, sentiment, fetched_at
           FROM news
           WHERE is_breaking = 1
             AND fetched_at >= datetime('now', '-2 hours')
             AND id NOT IN (SELECT COALESCE(json_extract(payload, '$.news_id'), '')
                            FROM alerts WHERE kind = 'HIGH_IMPACT_NEWS')"""
    ).fetchall()
    for nid, sym, source, title, url, sentiment, fetched in rows:
        msg = f"{(sym or '?')}: {title[:140]}"
        c.execute(
            "INSERT INTO alerts (symbol, kind, message, payload) VALUES (?, ?, ?, ?)",
            (sym or "?", "HIGH_IMPACT_NEWS", msg,
             json.dumps({"news_id": nid, "source": source, "url": url,
                          "sentiment": sentiment, "fetched_at": fetched})),
        )
        n += 1
    return n


def _check_crypto(c, cfg: dict) -> int:
    move_pct = float(cfg.get("price_move_pct", 5.0))
    n = 0
    rows = c.execute("""
        SELECT cp.symbol, cp.price_usd, cp.change_24h_pct
        FROM crypto_prices cp
        INNER JOIN (SELECT symbol, MAX(ts) m FROM crypto_prices GROUP BY symbol) lat
          ON cp.symbol=lat.symbol AND cp.ts=lat.m
    """).fetchall()
    for sym, price, chg in rows:
        if chg is not None and abs(chg) >= move_pct:
            direction = "up" if chg > 0 else "down"
            n += _emit(c, sym, "CRYPTO_MOVE",
                       f"{sym} {direction} {chg:+.2f}% 24h (${price:,.2f})",
                       {"pct": chg, "price": price})
    return n


def run() -> dict:
    cfg = (load_watchlist().get("alerts") or {})
    counts: dict[str, int] = {}
    with sqlite3.connect(DB_PATH) as c:
        counts["price_volume"] = _check_prices(c, cfg)
        counts["earnings"] = _check_earnings(c, cfg)
        counts["sentiment"] = _check_sentiment_surge(c, cfg)
        counts["macro"] = _check_macro(c, cfg)
        counts["crypto"] = _check_crypto(c, cfg)
        counts["breaking_news"] = _check_breaking_news(c, cfg)
        c.commit()
    counts["total_new"] = sum(counts.values())
    return counts


def fetch_unsent() -> list[sqlite3.Row]:
    """Return alerts not yet pushed externally (seen=0)."""
    with sqlite3.connect(DB_PATH) as c:
        c.row_factory = sqlite3.Row
        return c.execute(
            "SELECT id, symbol, kind, message, payload, created_at FROM alerts WHERE seen=0 ORDER BY id ASC"
        ).fetchall()


def mark_sent(ids: list[int]) -> None:
    if not ids:
        return
    with sqlite3.connect(DB_PATH) as c:
        c.executemany("UPDATE alerts SET seen=1 WHERE id=?", [(i,) for i in ids])
        c.commit()


if __name__ == "__main__":
    print(run())
