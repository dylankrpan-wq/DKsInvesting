"""Market-wide scan — find opportunities across the WHOLE market, not just the
watchlist.

Backbone is the movers feed (gainers/losers/most-active), which already carries
price, % change, volume and market cap in one call — so we score hundreds of
names with ZERO per-ticker fetches. Each is enriched with the news sentiment and
Reddit mentions we already collect, then ranked by a 'heat' score.

Results land in the `candidates` table (discovered_via='market_scan') and feed
the 📡 Now briefing's market-wide section + the Discover tab.
"""
from __future__ import annotations
import sqlite3
from dk.config import DB_PATH, equity_symbols
from dk.sources import market_movers
from dk.store import db as store

MIN_MARKET_CAP = 100_000_000   # skip sub-$100M micro/penny noise
MIN_PRICE = 1.0
TOP_N = 60


def _news_for(c, symbol: str) -> tuple[int, float | None]:
    row = c.execute(
        """SELECT COUNT(*), AVG(sentiment) FROM news
           WHERE symbol=? AND sentiment IS NOT NULL
             AND fetched_at >= datetime('now', '-2 days')""",
        (symbol,),
    ).fetchone()
    return (row[0] or 0, row[1])


def _reddit_for(c, symbol: str) -> int:
    row = c.execute(
        "SELECT COALESCE(SUM(mention_count),0) FROM trending_mentions WHERE symbol=?",
        (symbol,),
    ).fetchone()
    return int(row[0] or 0)


def _heat(change_pct, vol, avg_vol, news_n, news_sent, reddit_n) -> tuple[float, str, list[str]]:
    heat = 0.0
    reasons: list[str] = []

    if change_pct is not None:
        mag = min(abs(change_pct), 30.0)
        heat += mag * 1.6
        reasons.append(f"{change_pct:+.1f}% today")

    if vol and avg_vol and avg_vol > 0:
        ratio = vol / avg_vol
        if ratio >= 1.5:
            heat += min(ratio, 6) * 4
            reasons.append(f"{ratio:.1f}x avg volume")

    if news_n:
        heat += min(news_n, 5) * 3
        reasons.append(f"{news_n} recent headlines")
    if news_sent is not None and abs(news_sent) >= 0.1:
        heat += abs(news_sent) * 12
        reasons.append(f"news tone {news_sent:+.2f}")

    if reddit_n:
        heat += min(reddit_n, 10) * 1.2
        reasons.append(f"{reddit_n} reddit mentions")

    # direction: blend price move + news tone
    score_dir = 0
    if change_pct is not None:
        score_dir += change_pct
    if news_sent is not None:
        score_dir += news_sent * 20
    direction = "bull" if score_dir > 1 else ("bear" if score_dir < -1 else "flat")

    return round(min(heat, 100.0), 1), direction, reasons


def scan() -> dict:
    movers = market_movers.fetch_movers()
    if not movers:
        return {"movers": 0, "stored": 0, "note": "no movers source available (news/reddit still cover market)"}

    watch = set(equity_symbols())
    scored: list[dict] = []
    with sqlite3.connect(DB_PATH) as c:
        for m in movers:
            sym = m["symbol"]
            mcap = m.get("market_cap")
            price = m.get("price")
            if mcap is not None and mcap < MIN_MARKET_CAP:
                continue
            if price is not None and price < MIN_PRICE:
                continue

            news_n, news_sent = _news_for(c, sym)
            reddit_n = _reddit_for(c, sym)
            heat, direction, reasons = _heat(
                m.get("change_pct"), m.get("volume"), m.get("avg_volume"),
                news_n, news_sent, reddit_n,
            )
            scored.append({
                "symbol": sym,
                "name": m.get("name", sym),
                "sector": "?",
                "market_cap": mcap,
                "last_price": price,
                "mention_count": news_n + reddit_n,
                "discovered_via": "market_scan",
                "score": heat,
                "score_direction": direction,
                "notes": " · ".join(reasons[:4]),
                "on_watchlist": 1 if sym in watch else 0,
            })

    scored.sort(key=lambda x: x["score"], reverse=True)
    top = scored[:TOP_N]

    # Enrich the hottest names with technical signals (RSI/MACD/crosses/breakouts).
    # Best-effort: needs price history, so we fetch it for just the top dozen.
    try:
        from dk.sources import prices_yfinance
        from dk.indicators import signals as tech_signals
        for r in top[:12]:
            sym = r["symbol"]
            try:
                with sqlite3.connect(DB_PATH) as c2:
                    have = c2.execute("SELECT COUNT(*) FROM prices WHERE symbol=?", (sym,)).fetchone()[0]
                if have < 30:
                    prices_yfinance.fetch_prices(sym)
                summ = tech_signals.summarize(sym)
                if summ["signals"]:
                    top_sig = summ["signals"][0]
                    r["notes"] = (r.get("notes", "") + " · 📐 " + top_sig["label"]).strip(" ·")
                    # Boost heat when technicals CONFIRM the direction
                    if summ["net_lean"] == r["score_direction"] and r["score_direction"] in ("bull", "bear"):
                        confirm = summ["bull"] if r["score_direction"] == "bull" else summ["bear"]
                        r["score"] = min(100.0, r["score"] + confirm * 1.5)
            except Exception:
                continue
        top.sort(key=lambda x: x["score"], reverse=True)
    except Exception as e:
        print(f"[market_scan] tech enrichment skipped: {e}")

    # Persist (reuse candidates table; drop on_watchlist before upsert)
    rows = [{k: v for k, v in r.items() if k != "on_watchlist"} for r in top]
    store.upsert_candidates(rows)

    return {
        "movers": len(movers),
        "scored": len(scored),
        "stored": len(top),
        "top5": [{"symbol": r["symbol"], "heat": r["score"], "dir": r["score_direction"]}
                 for r in top[:5]],
    }


def top_market_opportunities(limit: int = 12, exclude_watchlist: bool = False) -> list[dict]:
    """Read the highest-heat market-scan candidates for the briefing/Discover."""
    watch = set(equity_symbols())
    with sqlite3.connect(DB_PATH) as c:
        c.row_factory = sqlite3.Row
        rows = c.execute(
            """SELECT symbol, name, score, score_direction, last_price, market_cap,
                      mention_count, notes
               FROM candidates
               WHERE discovered_via='market_scan'
               ORDER BY score DESC LIMIT 120""",
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["on_watchlist"] = d["symbol"] in watch
        if exclude_watchlist and d["on_watchlist"]:
            continue
        out.append(d)
        if len(out) >= limit:
            break
    return out
