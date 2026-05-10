"""IPO calendar via Finnhub (free tier requires key) + SEC EDGAR S-1 RSS fallback."""
from __future__ import annotations
import hashlib
from datetime import date, timedelta
import requests
import feedparser
from dk.config import get_key
from dk.store import db


def _hash(*parts: str) -> str:
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:24]


def fetch_finnhub(days_ahead: int = 90) -> int:
    key = get_key("FINNHUB_KEY")
    if not key:
        return 0
    today = date.today()
    end = today + timedelta(days=days_ahead)
    try:
        r = requests.get(
            "https://finnhub.io/api/v1/calendar/ipo",
            params={"from": today.isoformat(), "to": end.isoformat(), "token": key},
            timeout=15,
        )
        if r.status_code != 200:
            print(f"[finnhub-ipo] HTTP {r.status_code}")
            return 0
        data = r.json()
    except Exception as e:
        print(f"[finnhub-ipo] {e}")
        return 0
    rows = []
    for ipo in data.get("ipoCalendar", []) or []:
        sym = ipo.get("symbol") or ""
        d = ipo.get("date") or ""
        rows.append({
            "id": _hash("finnhub", sym, d),
            "symbol": sym,
            "name": ipo.get("name"),
            "expected_date": d,
            "price_range": ipo.get("price"),
            "shares": ipo.get("numberOfShares"),
            "exchange": ipo.get("exchange"),
            "source": "finnhub",
        })
    return db.upsert_ipos(rows)


def fetch_sec_s1() -> int:
    """Fallback: SEC EDGAR atom feed of recent S-1 filings (initial public offering registrations)."""
    url = "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=S-1&output=atom"
    try:
        feed = feedparser.parse(url, request_headers={"User-Agent": "DK-Investing/0.1 contact@example.com"})
    except Exception as e:
        print(f"[sec-s1] {e}")
        return 0
    rows = []
    for entry in feed.entries[:50]:
        title = entry.get("title", "")
        link = entry.get("link", "")
        published = entry.get("updated") or entry.get("published") or ""
        if not link:
            continue
        rows.append({
            "id": _hash("sec-s1", link),
            "symbol": None,
            "name": title[:200],
            "expected_date": published[:10],
            "price_range": None,
            "shares": None,
            "exchange": None,
            "source": f"SEC S-1 | {link}",
        })
    return db.upsert_ipos(rows)


def fetch_all() -> int:
    return fetch_finnhub() + fetch_sec_s1()
