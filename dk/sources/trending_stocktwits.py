"""StockTwits trending stream (public, no auth)."""
from __future__ import annotations
import requests
from dk.store import db


def fetch() -> int:
    url = "https://api.stocktwits.com/api/2/streams/trending.json"
    try:
        r = requests.get(url, timeout=12, headers={"User-Agent": "DK-Investing/0.1"})
        if r.status_code != 200:
            print(f"[stocktwits] HTTP {r.status_code}")
            return 0
        data = r.json()
    except Exception as e:
        print(f"[stocktwits] {e}")
        return 0

    counts: dict[str, dict] = {}
    bull = bear = 0
    for msg in data.get("messages", []) or []:
        ent = msg.get("entities") or {}
        # StockTwits messages can carry sentiment label "Bullish" / "Bearish"
        senti = (ent.get("sentiment") or {}).get("basic")
        for sym in (msg.get("symbols") or []):
            t = sym.get("symbol")
            if not t:
                continue
            if t not in counts:
                counts[t] = {"count": 0, "bull": 0, "bear": 0}
            counts[t]["count"] += 1
            if senti == "Bullish":
                counts[t]["bull"] += 1
            elif senti == "Bearish":
                counts[t]["bear"] += 1

    rows = []
    for sym, d in counts.items():
        net = (d["bull"] - d["bear"]) / max(1, d["bull"] + d["bear"]) if (d["bull"] + d["bear"]) else None
        rows.append({
            "symbol": sym.upper(),
            "source": "stocktwits",
            "mention_count": d["count"],
            "sentiment": net,
        })
    if not rows:
        return 0
    from dk.store.db import conn
    with conn() as c:
        c.execute("DELETE FROM trending_mentions WHERE source='stocktwits'")
        c.executemany("""
            INSERT OR REPLACE INTO trending_mentions
              (symbol, source, mention_count, sentiment)
            VALUES (:symbol, :source, :mention_count, :sentiment)
        """, rows)
    return len(rows)
