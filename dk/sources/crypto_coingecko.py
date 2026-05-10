from __future__ import annotations
from datetime import datetime, timezone
import requests
from dk.store import db


def fetch_prices(pairs: list[tuple[str, str]]) -> int:
    """pairs: [(SYMBOL, coingecko_id), ...]"""
    if not pairs:
        return 0
    ids = ",".join(p[1] for p in pairs)
    try:
        r = requests.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={
                "ids": ids,
                "vs_currencies": "usd",
                "include_market_cap": "true",
                "include_24hr_vol": "true",
                "include_24hr_change": "true",
            },
            timeout=15,
        )
        if r.status_code != 200:
            print(f"[coingecko] HTTP {r.status_code}")
            return 0
        data = r.json()
    except Exception as e:
        print(f"[coingecko] {e}")
        return 0

    ts = datetime.now(timezone.utc).isoformat()
    rows = []
    for sym, cid in pairs:
        d = data.get(cid)
        if not d:
            continue
        rows.append({
            "symbol": sym,
            "ts": ts,
            "price_usd": d.get("usd"),
            "market_cap": d.get("usd_market_cap"),
            "vol_24h": d.get("usd_24h_vol"),
            "change_24h_pct": d.get("usd_24h_change"),
        })
    return db.upsert_crypto(rows)
