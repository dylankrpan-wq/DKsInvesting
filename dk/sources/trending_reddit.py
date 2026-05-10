"""Reddit r/wallstreetbets and r/stocks ticker mentions.

Uses the public reddit JSON API (no key required, but UA must be set).
"""
from __future__ import annotations
import re
import requests
from dk.store import db

UA = "DK-Investing/0.1 (personal research tool)"
TICKER_RE = re.compile(r'\b\$?([A-Z]{2,5})\b')

# Aggressive stoplist (mirror the discovery scanner's denylist)
STOPS = {
    "THE","AND","FOR","CEO","CFO","SEC","IPO","CPI","NFP","FED","ETF","ESG","WSB",
    "USA","NYC","UK","EU","UN","AI","ML","API","TV","PE","PEG","ROI","ROE","EPS",
    "USD","EUR","GBP","JPY","CAD","HKD","INR","NEW","NOW","TOP","LET","NOT","CAN",
    "OUR","ITS","HAS","HAD","WAS","WHO","WHY","HOW","BIG","DAY","ONE","TWO","WIN",
    "GET","GOT","WILL","JUST","MORE","ONLY","OVER","WHEN","WITH","INTO","BACK",
    "DEAL","FIRM","FROM","HIGH","LIFE","MAKE","NEED","NEWS","PART","RATE","RISE",
    "RISK","SAID","SEEN","SIDE","TELL","TOLD","TURN","WANT","KEEP","LEAD","LATE",
    "WORK","BANK","FUND","RATES","STOCK","GAINS","LOSS","SAYS","SECTOR","MARKET",
    "DD","YOLO","TLDR","FOMO","GG","WSJ","CNBC","CNN","BBC","FOX","FT","BTC","ETH",
}


def _fetch_subreddit(name: str, limit: int = 50) -> list[dict]:
    url = f"https://www.reddit.com/r/{name}/hot.json"
    headers = {"User-Agent": UA}
    try:
        r = requests.get(url, headers=headers, params={"limit": limit}, timeout=12)
        if r.status_code != 200:
            print(f"[reddit/{name}] HTTP {r.status_code}")
            return []
        return [c["data"] for c in r.json().get("data", {}).get("children", [])]
    except Exception as e:
        print(f"[reddit/{name}] {e}")
        return []


def _count_tickers(posts: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for p in posts:
        text = (p.get("title") or "") + " " + (p.get("selftext") or "")
        # Prefer $TICKER pattern, fall back to caps tokens. Score $ matches higher.
        for m in re.findall(r'\$([A-Z]{1,5})\b', text):
            sym = m.upper()
            if sym in STOPS:
                continue
            counts[sym] = counts.get(sym, 0) + 3
        for m in TICKER_RE.findall(text):
            sym = m.upper()
            if sym in STOPS or len(sym) < 2:
                continue
            counts[sym] = counts.get(sym, 0) + 1
    return counts


def fetch(min_count: int = 3) -> int:
    rows = []
    for sub in ("wallstreetbets", "stocks"):
        posts = _fetch_subreddit(sub)
        c = _count_tickers(posts)
        for sym, n in c.items():
            if n < min_count:
                continue
            rows.append({
                "symbol": sym,
                "source": f"reddit_{sub.replace('wallstreetbets', 'wsb')}",
                "mention_count": n,
                "sentiment": None,
            })
    if not rows:
        return 0
    from dk.store.db import conn
    with conn() as conn_:
        # Reset all rows for these sources, then re-insert (snapshot semantics)
        conn_.execute(
            "DELETE FROM trending_mentions WHERE source IN ('reddit_wsb','reddit_stocks')"
        )
        conn_.executemany("""
            INSERT OR REPLACE INTO trending_mentions
              (symbol, source, mention_count, sentiment)
            VALUES (:symbol, :source, :mention_count, :sentiment)
        """, rows)
    return len(rows)
