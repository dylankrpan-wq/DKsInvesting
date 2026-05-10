"""Themes — load definitions from config/themes.yaml and score them."""
from __future__ import annotations
import sqlite3
import time
from datetime import datetime, timezone
import yaml
import yfinance as yf
from dk.config import CONFIG_DIR, DB_PATH
from dk.opportunity.score import score_symbol
from dk.sources import prices_yfinance


def load_themes() -> list[dict]:
    path = CONFIG_DIR / "themes.yaml"
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data.get("themes") or []


def _ensure_priced(symbol: str, c) -> bool:
    """Return True if we have at least 2 price bars cached for this symbol."""
    n = c.execute("SELECT COUNT(*) FROM prices WHERE symbol=?", (symbol,)).fetchone()[0]
    return n >= 2


def score_theme(theme: dict, fetch_missing: bool = False) -> dict:
    """Score a theme. Returns dict with aggregate metrics + top contributors.

    If `fetch_missing` is True, will pull prices for any constituent that has
    no cached data. Keep this off in scheduled polling for non-watchlist tickers
    to avoid N×yfinance hits per run.
    """
    constituents = theme.get("constituents") or []
    rows = []
    with sqlite3.connect(DB_PATH) as c:
        for sym in constituents:
            if fetch_missing and not _ensure_priced(sym, c):
                try:
                    prices_yfinance.fetch_prices(sym, period="3mo", interval="1d")
                    time.sleep(0.2)
                except Exception:
                    pass
            try:
                s = score_symbol(c, sym)
                # Latest day price change
                last2 = c.execute(
                    "SELECT close FROM prices WHERE symbol=? ORDER BY ts DESC LIMIT 2",
                    (sym,),
                ).fetchall()
                pchg = None
                if len(last2) == 2 and last2[0][0] and last2[1][0]:
                    pchg = (last2[0][0] - last2[1][0]) / last2[1][0] * 100
                # 24h sentiment
                sent_row = c.execute(
                    """SELECT AVG(sentiment), COUNT(*) FROM news
                       WHERE symbol=? AND sentiment IS NOT NULL
                         AND fetched_at >= datetime('now', '-1 day')""",
                    (sym,),
                ).fetchone()
                sent = sent_row[0] if sent_row else None
                rows.append({
                    "symbol": sym,
                    "score": s.score,
                    "direction": s.direction,
                    "sentiment": s.sentiment,
                    "sentiment_24h": sent,
                    "price_chg_1d": pchg,
                })
            except Exception as e:
                print(f"[theme {theme['id']}] {sym}: {e}")

    if not rows:
        return {**theme, "aggregate_score": 0, "constituents_scored": []}

    avg_score = sum(r["score"] for r in rows) / len(rows)
    sentiments = [r["sentiment"] for r in rows if r["sentiment"] is not None]
    avg_sent = sum(sentiments) / len(sentiments) if sentiments else 0
    pchgs = [r["price_chg_1d"] for r in rows if r["price_chg_1d"] is not None]
    avg_pchg = sum(pchgs) / len(pchgs) if pchgs else 0

    rows.sort(key=lambda r: r["score"], reverse=True)
    top = rows[0]["symbol"] if rows else None

    return {
        **theme,
        "aggregate_score": round(avg_score, 1),
        "avg_sentiment": round(avg_sent, 3),
        "avg_price_chg_1d": round(avg_pchg, 2),
        "constituent_count": len(rows),
        "top_contributor": top,
        "constituents_scored": rows,
    }


def score_all(fetch_missing: bool = False) -> list[dict]:
    out = [score_theme(t, fetch_missing=fetch_missing) for t in load_themes()]
    out.sort(key=lambda t: t["aggregate_score"], reverse=True)
    # Persist snapshot
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with sqlite3.connect(DB_PATH) as c:
        c.executemany(
            """INSERT OR REPLACE INTO theme_scores
               (theme_id, snapshot_ts, aggregate_score, avg_sentiment, avg_price_chg_1d,
                constituent_count, top_contributor)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            [(t["id"], now, t["aggregate_score"], t.get("avg_sentiment", 0),
              t.get("avg_price_chg_1d", 0), t.get("constituent_count", 0),
              t.get("top_contributor")) for t in out],
        )
        c.commit()
    return out


def theme_news(theme: dict, limit: int = 5) -> list[dict]:
    """Pull recent positive-sentiment news across the theme's constituents — the 'why'."""
    syms = theme.get("constituents") or []
    if not syms:
        return []
    placeholders = ",".join("?" * len(syms))
    with sqlite3.connect(DB_PATH) as c:
        c.row_factory = sqlite3.Row
        rows = c.execute(
            f"""SELECT symbol, title, url, source, sentiment, published, fetched_at
                FROM news
                WHERE symbol IN ({placeholders})
                  AND sentiment IS NOT NULL
                  AND fetched_at >= datetime('now', '-7 days')
                ORDER BY ABS(sentiment) DESC, fetched_at DESC LIMIT ?""",
            (*syms, limit),
        ).fetchall()
        return [dict(r) for r in rows]
