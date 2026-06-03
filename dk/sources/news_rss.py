from __future__ import annotations
import hashlib
import feedparser
from dk.store import db

# Free RSS feeds — no key required.
GLOBAL_FEEDS = [
    # Wire services and primary newsrooms
    ("Yahoo Finance", "https://finance.yahoo.com/news/rssindex", "GLOBAL"),
    ("Reuters Business", "https://feeds.reuters.com/reuters/businessNews", "GLOBAL"),
    ("Reuters Markets", "https://feeds.reuters.com/news/wealth", "GLOBAL"),
    ("CNBC Top News", "https://www.cnbc.com/id/100003114/device/rss/rss.html", "US"),
    ("CNBC Markets", "https://www.cnbc.com/id/15839069/device/rss/rss.html", "US"),
    ("CNBC Earnings", "https://www.cnbc.com/id/15839135/device/rss/rss.html", "US"),
    ("MarketWatch Top", "https://feeds.content.dowjones.io/public/rss/mw_topstories", "US"),
    ("MarketWatch RealTime", "https://feeds.content.dowjones.io/public/rss/mw_realtimeheadlines", "US"),
    ("WSJ Markets", "https://feeds.a.dj.com/rss/RSSMarketsMain.xml", "US"),
    ("FT Companies", "https://www.ft.com/companies?format=rss", "GLOBAL"),
    ("FT Markets", "https://www.ft.com/markets?format=rss", "GLOBAL"),

    # Fast-breaking financial press
    ("Benzinga Top", "https://www.benzinga.com/feed", "US"),
    ("Seeking Alpha Top", "https://seekingalpha.com/feed.xml", "US"),
    ("Investing.com News", "https://www.investing.com/rss/news.rss", "GLOBAL"),

    # Company press release wires (contracts, M&A, FDA approvals, earnings releases)
    ("PR Newswire All", "https://www.prnewswire.com/rss/news-releases-list.rss", "GLOBAL"),
    ("GlobeNewswire", "https://www.globenewswire.com/RssFeed/orgclass/1/feedTitle/GlobeNewswire%20-%20All%20Press%20Releases", "GLOBAL"),
    ("BusinessWire", "https://feed.businesswire.com/rss/home/?rss=G1QFDERJXkJfQ1FaXQNDXFRMUVc=", "GLOBAL"),

    # Official sources (Fed / SEC / Treasury — highest signal-to-noise)
    ("SEC EDGAR 8-K", "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=8-K&output=atom", "US"),
    ("SEC Press Releases", "https://www.sec.gov/news/pressreleases.rss", "US"),
    ("Federal Reserve Press", "https://www.federalreserve.gov/feeds/press_all.xml", "US"),
    ("Treasury Press", "https://home.treasury.gov/news/press-releases/feed", "US"),

    # International
    ("Reuters Europe", "https://feeds.reuters.com/reuters/UKBusinessNews", "EU"),
    ("Nikkei Asia", "https://asia.nikkei.com/rss/feed/nar", "ASIA"),

    # Power players — direct primary-source feeds (highest signal)
    ("Trump Truth Social", "https://trumpstruth.org/feed", "US"),
    ("White House", "https://www.whitehouse.gov/feed/", "US"),
    ("White House Briefing Room", "https://www.whitehouse.gov/briefing-room/feed/", "US"),
]

# Crypto-specific high-signal feeds
CRYPTO_FEEDS = [
    ("CoinDesk", "https://www.coindesk.com/arc/outboundfeeds/rss/", "CRYPTO"),
    ("The Block", "https://www.theblock.co/rss.xml", "CRYPTO"),
    ("Decrypt", "https://decrypt.co/feed", "CRYPTO"),
    ("CoinTelegraph", "https://cointelegraph.com/rss", "CRYPTO"),
]

# High-impact keywords for "breaking news" classification
HIGH_IMPACT_KEYWORDS = [
    # M&A and deals
    "acquires", "acquisition", "merger", "buyout", "takeover", "to acquire",
    "definitive agreement", "to merge", "spinoff", "spin-off", "joint venture",
    # Regulatory / legal
    "fda approves", "fda approval", "fda rejects", "clinical trial",
    "phase 3", "phase iii", "breakthrough designation",
    "sec charges", "sec investigation", "doj", "antitrust", "subpoena",
    "lawsuit", "settles", "settlement", "fined", "indicted",
    # Financial events
    "bankruptcy", "files for chapter 11", "delisted", "halted",
    "guidance cut", "guidance raised", "guidance lowered", "guidance increased",
    "beats estimates", "misses estimates", "tops estimates",
    "raises guidance", "cuts guidance", "withdraws guidance",
    "dividend increase", "dividend cut", "suspends dividend",
    "buyback", "share repurchase", "stock split",
    # Operational / contracts
    "wins contract", "awarded contract", "partnership",
    "signs deal", "to supply", "secures contract",
    # Executives
    "ceo resigns", "ceo steps down", "ceo fired", "appoints ceo",
    # Crypto-specific
    "etf approved", "etf rejected", "hard fork", "exploit", "hacked",
    "lawsuit dismissed",
    # Conferences / keynotes / product launches (Jensen's GTC, Apple WWDC, etc.)
    "keynote", "gtc", "wwdc", "investor day", "analyst day", "investor meeting",
    "shareholder meeting", "annual meeting", "developer conference",
    "ai summit", "tech summit",
    "unveils", "unveiled", "reveals", "revealed", "introduces", "introduced",
    "launches", "launched", "debuts", "debuted", "showcases",
    "announces new", "announces partnership", "announces deal",
    "announced today", "announces collaboration", "announces strategic",
    # Earnings call commentary
    "raises full-year", "raises full year", "tops revenue", "tops earnings",
    "blowout quarter", "record revenue", "record earnings", "record bookings",
    "record backlog", "record demand", "record orders",
    # AI / chip cycle (relevant for NVDA, AMD, etc.)
    "next generation", "next-gen", "new chip", "supercomputer",
    "data center", "ai factory", "ai chip", "ai accelerator",
    # Powell / macro speeches
    "powell speaks", "powell says", "fed chair", "fomc minutes",
    "dot plot", "rate cut", "rate hike", "rate decision",
]



def _yahoo_ticker_feed(sym: str) -> str:
    return f"https://finance.yahoo.com/rss/headline?s={sym}"


def _hash_id(*parts: str) -> str:
    h = hashlib.sha1("|".join(parts).encode("utf-8", errors="ignore")).hexdigest()
    return h[:24]


def _is_high_impact(text: str) -> bool:
    text_lower = (text or "").lower()
    return any(kw in text_lower for kw in HIGH_IMPACT_KEYWORDS)


def _parse(url: str, source: str, region: str, symbol: str | None = None) -> list[dict]:
    out = []
    try:
        feed = feedparser.parse(url, request_headers={"User-Agent": "DK-Investing/0.1 (research)"})
    except Exception as e:
        print(f"[rss] {source}: {e}")
        return out
    for entry in feed.entries[:50]:
        title = entry.get("title", "").strip()
        link = entry.get("link", "")
        if not title or not link:
            continue
        published = entry.get("published") or entry.get("updated") or ""
        summary = entry.get("summary", "")[:1000]
        is_breaking = _is_high_impact(title + " " + summary)
        out.append({
            "id": _hash_id(source, link),
            "symbol": symbol,
            "region": region,
            "source": source,
            "title": title,
            "summary": summary,
            "url": link,
            "published": published,
            "is_breaking": 1 if is_breaking else 0,
        })
    return out


def fetch_global() -> int:
    rows: list[dict] = []
    for source, url, region in GLOBAL_FEEDS:
        rows.extend(_parse(url, source, region))
    return db.upsert_news(rows)


def fetch_crypto() -> int:
    rows: list[dict] = []
    for source, url, region in CRYPTO_FEEDS:
        rows.extend(_parse(url, source, region))
    return db.upsert_news(rows)


def fetch_per_ticker(symbols: list[str]) -> int:
    rows: list[dict] = []
    for s in symbols:
        rows.extend(_parse(_yahoo_ticker_feed(s), f"Yahoo:{s}", "US", symbol=s))
    return db.upsert_news(rows)
