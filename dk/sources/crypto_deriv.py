"""Blofin perpetual-swap (derivatives) market data — public, keyless.

fetch_tickers(): one request returns every listed perp (~500), cheap enough to
poll on a sub-minute timer (used by dk/jobs/crypto_spike.py).
fetch_candles() / fetch_funding() / fetch_ticker(): per-instrument detail used
by dk/analysis/perp.py for on-demand structure analysis.

Spot/positions auth lives in dk/brokers/blofin.py; this only touches public
market endpoints.
"""
from __future__ import annotations
import requests

BASE = "https://openapi.blofin.com"


def _get(path: str, params: dict, timeout: int = 12):
    try:
        r = requests.get(BASE + path, params=params, timeout=timeout)
        if r.status_code != 200:
            print(f"[crypto_deriv] {path} HTTP {r.status_code}: {r.text[:160]}")
            return None
        data = r.json()
        if str(data.get("code")) != "0":
            print(f"[crypto_deriv] {path} API error: {data.get('msg', data)}")
            return None
        return data.get("data")
    except Exception as e:
        print(f"[crypto_deriv] {path} {e}")
        return None


def _ticker_row(row: dict) -> dict | None:
    try:
        last = float(row.get("last") or 0)
        if last <= 0:
            return None
        open24 = float(row.get("open24h") or 0)
        high24 = float(row.get("high24h") or 0)
        low24 = float(row.get("low24h") or 0)
        base_vol = float(row.get("volCurrency24h") or 0)
        return {
            "inst_id": row.get("instId"),
            "last": last,
            "open24h": open24,
            "high24h": high24,
            "low24h": low24,
            "quote_vol_usd": base_vol * last,
            "chg_24h_pct": ((last - open24) / open24 * 100.0) if open24 > 0 else None,
        }
    except (TypeError, ValueError):
        return None


def fetch_tickers(inst_type: str = "SWAP", timeout: int = 12) -> list[dict]:
    """All perp tickers. Empty list on failure (a missed tick is a no-op)."""
    data = _get("/api/v1/market/tickers", {"instType": inst_type}, timeout)
    if not data:
        return []
    return [r for r in (_ticker_row(x) for x in data) if r]


def fetch_ticker(inst_id: str, timeout: int = 12) -> dict | None:
    """Single perp ticker (24h o/h/l/c + USD turnover)."""
    data = _get("/api/v1/market/tickers", {"instId": inst_id}, timeout)
    if not data:
        return None
    return _ticker_row(data[0]) if data else None


def fetch_candles(inst_id: str, bar: str = "1H", limit: int = 48,
                  timeout: int = 12) -> list[dict]:
    """OHLCV candles, oldest-first. bar: 1m/3m/5m/15m/30m/1H/4H/1D etc."""
    data = _get("/api/v1/market/candles",
                {"instId": inst_id, "bar": bar, "limit": limit}, timeout)
    if not data:
        return []
    out = []
    for x in data:
        try:
            out.append({"ts": int(x[0]), "open": float(x[1]), "high": float(x[2]),
                        "low": float(x[3]), "close": float(x[4]), "vol": float(x[5])})
        except (TypeError, ValueError, IndexError):
            continue
    out.sort(key=lambda r: r["ts"])  # oldest first
    return out


def fetch_funding(inst_id: str, timeout: int = 12) -> float | None:
    """Current funding rate as a fraction (e.g. 0.0001 = 0.01%)."""
    data = _get("/api/v1/market/funding-rate", {"instId": inst_id}, timeout)
    if not data:
        return None
    try:
        return float(data[0].get("fundingRate"))
    except (TypeError, ValueError, IndexError):
        return None
