"""Per-ticker news via newsapi.ai (Event Registry).

The user's NEWSAPI_KEY is an Event Registry (newsapi.ai) UUID key — a different
service from newsapi.org (which news_newsapi.py targets). Event Registry's
getArticles returns rich structured articles by keyword.

Free tier is token-limited, so we ROTATE through the priority universe a few
names per poll and enforce a hard daily call budget (state persisted in
DATA_DIR). A quota/auth error stops spending for the rest of the day.
"""
from __future__ import annotations
import hashlib
import json
import time
from datetime import datetime, timedelta, timezone
import requests
from dk.config import get_key, DATA_DIR, equity_symbols, load_watchlist
from dk.store import db

_URL = "https://eventregistry.org/api/v1/article/getArticles"
_STATE = DATA_DIR / "newsapi_ai_state.json"


def is_eventregistry_key(key: str | None) -> bool:
    """Event Registry keys are UUIDs (8-4-4-4-12 hex, four dashes). newsapi.org
    keys are 32 hex chars with no dashes — so the dash count disambiguates."""
    return bool(key) and key.count("-") == 4 and len(key) >= 32


def _cfg() -> dict:
    try:
        return (load_watchlist() or {}).get("newsapi") or {}
    except Exception:
        return {}


def _load_state() -> dict:
    try:
        with open(_STATE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_state(st: dict) -> None:
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(_STATE, "w", encoding="utf-8") as f:
            json.dump(st, f)
    except Exception as e:
        print(f"[newsapi.ai] state save: {e}")


def _priority_universe() -> list[tuple[str, str | None]]:
    """(symbol, name) — watchlist equities/ETFs first, then named-portfolio tickers."""
    wl = load_watchlist() or {}
    names = {e["symbol"]: e.get("name")
             for e in (wl.get("equities") or []) + (wl.get("etfs") or [])}
    syms: list[str] = list(equity_symbols())
    try:
        from dk.jobs.portfolio_digest import all_portfolio_tickers
        for s in all_portfolio_tickers():
            if s not in syms:
                syms.append(s)
    except Exception:
        pass
    return [(s, names.get(s)) for s in syms]


def _hash_id(url: str) -> str:
    return hashlib.sha1(("eventregistry|" + url).encode()).hexdigest()[:24]


def _fetch_one(key: str, symbol: str, name: str | None, date_start: str) -> tuple[int, bool]:
    """Fetch articles for one name. Returns (rows_upserted, ok); ok=False on a
    quota/auth error so the caller stops spending for the day."""
    body = {
        "apiKey": key,
        "keyword": name or symbol,
        "keywordLoc": "title",          # title match = precise; relevance gate does the rest
        "lang": "eng",
        "dateStart": date_start,
        "articlesCount": 15,
        "articlesSortBy": "date",
        "resultType": "articles",
        "dataType": ["news"],
        "includeArticleBody": True,
        "includeArticleImage": False,
    }
    try:
        r = requests.post(_URL, json=body, timeout=20)
    except Exception as e:
        print(f"[newsapi.ai] {symbol}: {e}")
        return 0, True  # transient network — don't burn the whole day
    if r.status_code != 200:
        print(f"[newsapi.ai] {symbol}: HTTP {r.status_code} {r.text[:100]}")
        return 0, r.status_code not in (401, 429)  # bad key / rate-limited → stop
    try:
        data = r.json()
    except Exception:
        return 0, True
    if isinstance(data, dict) and data.get("error"):
        print(f"[newsapi.ai] {symbol}: {data.get('error')}")
        return 0, False  # token exhaustion etc.

    rows = []
    for a in ((data or {}).get("articles") or {}).get("results") or []:
        url = a.get("url") or ""
        if not url:
            continue
        src = (a.get("source") or {}).get("title") or "unknown"
        rows.append({
            "id": _hash_id(url),
            "symbol": symbol,
            "region": "GLOBAL",
            "source": f"NewsAPI.ai:{src}",
            "title": a.get("title", ""),
            "summary": (a.get("body") or "")[:1000],
            "url": url,
            "published": a.get("dateTimePub") or a.get("dateTime") or "",
        })
    from dk.sources.relevance import filter_relevant
    rows = filter_relevant(symbol, name, rows)
    return db.upsert_news(rows), True


def fetch_rotating() -> dict:
    """Fetch news for the next batch of priority names (rotating cursor) within a
    hard daily call budget. No-op unless NEWSAPI_KEY is an Event Registry key."""
    key = get_key("NEWSAPI_KEY")
    if not is_eventregistry_key(key):
        return {"configured": False}
    cfg = _cfg()
    if cfg.get("enabled") is False:
        return {"configured": True, "enabled": False}
    batch = int(cfg.get("batch_size", 4))
    budget = int(cfg.get("daily_budget", 80))

    today = datetime.now(timezone.utc).date().isoformat()
    st = _load_state()
    if st.get("date") != today:
        st = {"date": today, "used": 0, "cursor": st.get("cursor", 0)}
    used = int(st.get("used", 0))
    if used >= budget:
        return {"configured": True, "budget_hit": True, "used": used, "budget": budget}

    uni = _priority_universe()
    if not uni:
        return {"configured": True, "universe": 0}
    cursor = int(st.get("cursor", 0)) % len(uni)
    date_start = (datetime.now(timezone.utc) - timedelta(days=3)).date().isoformat()

    calls = rows_total = 0
    names: list[str] = []
    for _ in range(min(batch, budget - used, len(uni))):
        symbol, name = uni[cursor]
        cursor = (cursor + 1) % len(uni)
        n, ok = _fetch_one(key, symbol, name, date_start)
        calls += 1
        rows_total += n
        names.append(symbol)
        if not ok:
            break
        time.sleep(0.3)

    st["used"] = used + calls
    st["cursor"] = cursor
    _save_state(st)
    return {"configured": True, "calls": calls, "rows": rows_total,
            "names": names, "used_today": st["used"], "budget": budget}
