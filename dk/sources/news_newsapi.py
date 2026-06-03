from __future__ import annotations
import hashlib
import requests
from dk.config import get_key
from dk.store import db


def _hash_id(url: str) -> str:
    return hashlib.sha1(("newsapi|" + url).encode()).hexdigest()[:24]


def fetch_for_symbol(symbol: str, name: str | None = None) -> int:
    key = get_key("NEWSAPI_KEY")
    if not key:
        return 0
    # Build a precise query: prefer the exact company-name phrase. Only add the
    # bare symbol when it's long enough (>=4) to not match random words — short
    # tickers like "MU"/"T" as free-text are the main false-positive source.
    if name and len(symbol) >= 4:
        q = f'"{name}" OR {symbol}'
    elif name:
        q = f'"{name}"'
    else:
        q = symbol
    try:
        r = requests.get(
            "https://newsapi.org/v2/everything",
            params={"q": q, "language": "en", "sortBy": "publishedAt",
                    "searchIn": "title,description", "pageSize": 30, "apiKey": key},
            timeout=15,
        )
        if r.status_code != 200:
            print(f"[newsapi] {symbol}: HTTP {r.status_code}")
            return 0
        data = r.json()
    except Exception as e:
        print(f"[newsapi] {symbol}: {e}")
        return 0

    rows = []
    for a in data.get("articles", []):
        url = a.get("url") or ""
        if not url:
            continue
        rows.append({
            "id": _hash_id(url),
            "symbol": symbol,
            "region": "GLOBAL",
            "source": f"NewsAPI:{(a.get('source') or {}).get('name', 'unknown')}",
            "title": a.get("title", ""),
            "summary": (a.get("description") or "")[:1000],
            "url": url,
            "published": a.get("publishedAt", ""),
        })

    # Relevance gate — drop anything not directly about this company/ticker.
    from dk.sources.relevance import filter_relevant
    rows = filter_relevant(symbol, name, rows)
    return db.upsert_news(rows)
