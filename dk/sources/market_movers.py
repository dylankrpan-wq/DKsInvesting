"""Market-wide movers — the names actually moving across the WHOLE market today.

Tries multiple free sources and returns whatever works (resilient to datacenter
IP blocking). Each mover: {symbol, name, price, change_pct, volume, market_cap}.

Sources tried in order:
  1. Yahoo predefined screener (day_gainers / day_losers / most_actives)
  2. Financial Modeling Prep (if FMP_API_KEY set) — gainers/losers/actives
The news + Reddit layers (already market-wide) backstop this if both fail.
"""
from __future__ import annotations
import time
import requests
from dk.config import get_key

_UA = {"User-Agent": "Mozilla/5.0 (DK-Investing research)"}

# FMP free tier is 250 req/day — cache the movers pull so calling every poll
# (even when Yahoo is IP-blocked on Railway) can't exhaust the budget.
_FMP_CACHE: dict = {"ts": 0.0, "rows": []}
_FMP_TTL = 1200  # 20 minutes


def _from_yahoo(scr_id: str, count: int = 50) -> list[dict]:
    url = ("https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved"
           f"?count={count}&scrIds={scr_id}")
    try:
        r = requests.get(url, headers=_UA, timeout=15)
        if r.status_code != 200:
            return []
        data = r.json()
        quotes = (data.get("finance", {}).get("result") or [{}])[0].get("quotes", [])
    except Exception as e:
        print(f"[movers/yahoo {scr_id}] {e}")
        return []
    out = []
    for q in quotes:
        sym = q.get("symbol")
        if not sym:
            continue
        out.append({
            "symbol": sym.upper(),
            "name": q.get("shortName") or q.get("longName") or sym,
            "price": q.get("regularMarketPrice"),
            "change_pct": q.get("regularMarketChangePercent"),
            "volume": q.get("regularMarketVolume"),
            "avg_volume": q.get("averageDailyVolume3Month"),
            "market_cap": q.get("marketCap"),
            "bucket": scr_id,
        })
    return out


def _from_fmp_stable(path: str, bucket: str) -> list[dict]:
    key = get_key("FMP_API_KEY")
    if not key:
        return []
    url = f"https://financialmodelingprep.com/stable/{path}"
    try:
        r = requests.get(url, params={"apikey": key}, headers=_UA, timeout=15)
        if r.status_code != 200:
            print(f"[movers/fmp {path}] HTTP {r.status_code}")
            return []
        data = r.json()
    except Exception as e:
        print(f"[movers/fmp {path}] {e}")
        return []
    out = []
    for q in (data or []):
        sym = q.get("symbol")
        if not sym:
            continue
        out.append({
            "symbol": sym.upper(),
            "name": q.get("name") or sym,
            "price": q.get("price"),
            "change_pct": q.get("changesPercentage"),  # /stable field name
            "volume": None,
            "avg_volume": None,
            "market_cap": None,
            "bucket": bucket,
        })
    return out


def _fmp_all() -> list[dict]:
    """All three FMP mover buckets, cached for _FMP_TTL to protect the daily budget."""
    if not get_key("FMP_API_KEY"):
        return []
    now = time.time()
    if _FMP_CACHE["rows"] and now - _FMP_CACHE["ts"] < _FMP_TTL:
        return _FMP_CACHE["rows"]
    out: list[dict] = []
    for path, bucket in (("biggest-gainers", "gainers"),
                         ("biggest-losers", "losers"),
                         ("most-actives", "actives")):
        out.extend(_from_fmp_stable(path, bucket))
    _FMP_CACHE["ts"] = now            # throttle retries even on empty
    if out:
        _FMP_CACHE["rows"] = out
    return out or _FMP_CACHE["rows"]


def fetch_movers() -> list[dict]:
    """Return a de-duplicated list of market-wide movers from whatever source works.
    Yahoo is primary (has volume/mktcap); FMP supplements + backstops it when the
    datacenter IP is blocked (the common Railway case)."""
    by_symbol: dict[str, dict] = {}

    # Yahoo predefined screeners
    for scr in ("day_gainers", "day_losers", "most_actives"):
        for m in _from_yahoo(scr):
            by_symbol.setdefault(m["symbol"], m)

    # FMP supplement/backstop (cached; fills gaps + rescues a blocked Yahoo)
    if len(by_symbol) < 30:
        for m in _fmp_all():
            by_symbol.setdefault(m["symbol"], m)

    return list(by_symbol.values())
