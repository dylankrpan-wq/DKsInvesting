"""Leaderboards — top 25 stocks / ETFs / dividend stocks / crypto.

All from free, datacenter-friendly sources:
  - crypto  : CoinGecko /coins/markets (rich data, no key)
  - stocks  : Yahoo predefined screener 'most_actives' (price/change/marketCap)
  - etfs    : curated list (config/leaderboards.yaml) + Yahoo v8 chart price/change
  - dividend: curated list + v8 chart price/change; yield computed from config div
"""
from __future__ import annotations
import concurrent.futures
import requests
import yaml
from dk.config import CONFIG_DIR

_UA = {"User-Agent": "Mozilla/5.0 (DK-Investing research)"}


def _load_cfg() -> dict:
    path = CONFIG_DIR / "leaderboards.yaml"
    if not path.exists():
        return {"etfs": [], "dividend": []}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {"etfs": [], "dividend": []}


# ---------- Crypto (CoinGecko) ----------
def top_crypto(n: int = 25) -> list[dict]:
    try:
        r = requests.get(
            "https://api.coingecko.com/api/v3/coins/markets",
            params={"vs_currency": "usd", "order": "market_cap_desc",
                    "per_page": n, "page": 1, "price_change_percentage": "24h,7d"},
            headers=_UA, timeout=20,
        )
        if r.status_code != 200:
            return []
        data = r.json()
    except Exception as e:
        print(f"[leaderboards/crypto] {e}")
        return []
    out = []
    for c in data:
        out.append({
            "rank": c.get("market_cap_rank"),
            "symbol": (c.get("symbol") or "").upper(),
            "name": c.get("name"),
            "price": c.get("current_price"),
            "change_24h": c.get("price_change_percentage_24h"),
            "change_7d": c.get("price_change_percentage_7d_in_currency"),
            "market_cap": c.get("market_cap"),
            "volume": c.get("total_volume"),
        })
    return out


# ---------- Stocks (Yahoo screener) ----------
def top_stocks(n: int = 25) -> list[dict]:
    url = "https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved"
    try:
        r = requests.get(url, params={"count": n, "scrIds": "most_actives"},
                         headers=_UA, timeout=15)
        if r.status_code != 200:
            return []
        quotes = (r.json().get("finance", {}).get("result") or [{}])[0].get("quotes", [])
    except Exception as e:
        print(f"[leaderboards/stocks] {e}")
        return []
    out = []
    for q in quotes[:n]:
        out.append({
            "symbol": q.get("symbol"),
            "name": q.get("shortName") or q.get("longName") or q.get("symbol"),
            "price": q.get("regularMarketPrice"),
            "change_pct": q.get("regularMarketChangePercent"),
            "market_cap": q.get("marketCap"),
            "volume": q.get("regularMarketVolume"),
            "pe": q.get("trailingPE"),
        })
    return out


# ---------- v8 chart quote (any symbol) ----------
def _chart_quote(symbol: str) -> dict:
    try:
        r = requests.get(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
            params={"range": "5d", "interval": "1d"}, headers=_UA, timeout=12,
        )
        meta = r.json()["chart"]["result"][0]["meta"]
        price = meta.get("regularMarketPrice")
        prev = meta.get("chartPreviousClose") or meta.get("previousClose")
        chg = ((price - prev) / prev * 100) if (price and prev) else None
        return {"price": price, "change_pct": chg}
    except Exception:
        return {"price": None, "change_pct": None}


def _enrich(items: list[dict]) -> list[dict]:
    """Attach live price/change to a curated list, in parallel."""
    syms = [it["symbol"] for it in items]
    quotes: dict[str, dict] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
        for sym, q in zip(syms, ex.map(_chart_quote, syms)):
            quotes[sym] = q
    for it in items:
        q = quotes.get(it["symbol"], {})
        it["price"] = q.get("price")
        it["change_pct"] = q.get("change_pct")
    return items


def top_etfs() -> list[dict]:
    items = [dict(e) for e in (_load_cfg().get("etfs") or [])]
    return _enrich(items)


def top_dividend() -> list[dict]:
    items = [dict(e) for e in (_load_cfg().get("dividend") or [])]
    items = _enrich(items)
    for it in items:
        div = it.get("div")
        price = it.get("price")
        it["yield_pct"] = (div / price * 100) if (div and price) else None
    items.sort(key=lambda x: (x.get("yield_pct") or 0), reverse=True)
    return items
