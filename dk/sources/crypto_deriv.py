"""Blofin perpetual-swap (derivatives) ticker snapshot — public, keyless.

One request returns every listed perp (~500), so it's cheap enough to poll on a
sub-minute timer. Used by dk/jobs/crypto_spike.py to catch short-window pumps
like BEAT-USDT / TRUMP-USDT. Spot/positions auth lives in dk/brokers/blofin.py;
this only touches the public market endpoint.
"""
from __future__ import annotations
import requests

BASE = "https://openapi.blofin.com"
_ENDPOINT = "/api/v1/market/tickers"


def fetch_tickers(inst_type: str = "SWAP", timeout: int = 12) -> list[dict]:
    """Return [{inst_id, last, quote_vol_usd, chg_24h_pct}] for all perps.
    Empty list on any failure (caller treats a missed tick as a no-op)."""
    try:
        r = requests.get(BASE + _ENDPOINT, params={"instType": inst_type},
                         timeout=timeout)
        if r.status_code != 200:
            print(f"[crypto_deriv] HTTP {r.status_code}: {r.text[:160]}")
            return []
        data = r.json()
        if str(data.get("code")) != "0":
            print(f"[crypto_deriv] API error: {data.get('msg', data)}")
            return []
    except Exception as e:
        print(f"[crypto_deriv] {e}")
        return []

    out: list[dict] = []
    for row in (data.get("data") or []):
        try:
            last = float(row.get("last") or 0)
            if last <= 0:
                continue
            open24 = float(row.get("open24h") or 0)
            base_vol = float(row.get("volCurrency24h") or 0)  # 24h volume in base ccy
            chg_24h = ((last - open24) / open24 * 100.0) if open24 > 0 else None
            out.append({
                "inst_id": row.get("instId"),
                "last": last,
                "quote_vol_usd": base_vol * last,  # ≈ 24h USD turnover
                "chg_24h_pct": chg_24h,
            })
        except (TypeError, ValueError):
            continue
    return out
