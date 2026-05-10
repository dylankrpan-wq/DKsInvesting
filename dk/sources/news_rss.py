from __future__ import annotations
import hashlib
import feedparser
from dk.store import db

# Free RSS feeds — no key required.
GLOBAL_FEEDS = [
    ("Yahoo Finance", "https://finance.yahoo.com/news/rssindex", "GLOBAL"),
    ("Reuters Business", "https://feeds.reuters.com/reuters/businessNews", "GLOBAL"),
    ("CNBC Top News", "https://www.cnbc.com/id/100003114/device/rss/rss.html", "US"),
    ("CNBC Markets", "https://www.cnbc.com/id/15839069/device/rss/rss.html", "US"),
    ("MarketWatch Top", "https://feeds.content.dowjones.io/public/rss/mw_topstories", "US"),
    ("SEC EDGAR 8-K", "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=8-K&output=atom", "US"),
    ("FT Companies", "https://www.ft.com/companies?format=rss", "GLOBAL"),
]


def _yahoo_ticker_feed(sym: str) -> str:
    return f"https://finance.yahoo.com/rss/headline?s={sym}"


def _hash_id(*parts: str) -> str:
    h = hashlib.sha1("|".join(parts).encode("utf-8", errors="ignore")).hexdigest()
    return h[:24]


def _parse(url: str, source: str, region: str, symbol: str | None = None) -> list[dict]:
    out = []
    try:
        feed = feedparser.parse(url, request_headers={"User-Agent": "DK-Investing/0.1"})
    except Exception as e:
        print(f"[rss] {source}: {e}")
        return out
    for entry in feed.entries[:50]:
        title = entry.get("title", "").strip()
        link = entry.get("link", "")
        if not title or not link:
            continue
        published = entry.get("published") or entry.get("updated") or ""
        out.append({
            "id": _hash_id(source, link),
            "symbol": symbol,
            "region": region,
            "source": source,
            "title": title,
            "summary": entry.get("summary", "")[:1000],
            "url": link,
            "published": published,
        })
    return out


def fetch_global() -> int:
    rows: list[dict] = []
    for source, url, region in GLOBAL_FEEDS:
        rows.extend(_parse(url, source, region))
    return db.upsert_news(rows)


def fetch_per_ticker(symbols: list[str]) -> int:
    rows: list[dict] = []
    for s in symbols:
        rows.extend(_parse(_yahoo_ticker_feed(s), f"Yahoo:{s}", "US", symbol=s))
    return db.upsert_news(rows)
