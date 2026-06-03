"""Stooq price source — free daily OHLCV via CSV, works from datacenter IPs.

yfinance frequently gets rate-limited/blocked from cloud hosts (Railway, AWS,
etc.). Stooq serves a plain CSV with no key and no datacenter blocking, so it's
our server-side fallback for daily bars.

Endpoint: https://stooq.com/q/d/l/?s=<symbol>&i=d
US equities/ETFs use the `.us` suffix (lowercase). Returns:
    Date,Open,High,Low,Close,Volume
"""
from __future__ import annotations
import csv
import io
import requests
from dk.store import db

# Symbols that need special Stooq mapping (indices, etc.). Most US tickers just
# get `.us`. Add overrides here as needed.
SYMBOL_OVERRIDES = {
    "SPY": "spy.us", "QQQ": "qqq.us", "VOO": "voo.us",
    "IBIT": "ibit.us", "ETHE": "ethe.us",
}


def _stooq_symbol(symbol: str) -> str:
    s = symbol.upper()
    if s in SYMBOL_OVERRIDES:
        return SYMBOL_OVERRIDES[s]
    return f"{symbol.lower()}.us"


def fetch_prices(symbol: str, max_bars: int = 130) -> int:
    """Fetch daily bars from Stooq and store. Returns rows written (0 on failure).

    Stooq now gates CSV downloads behind an API key. Set STOOQ_API_KEY in env to
    enable; otherwise this skips immediately (no wasted request)."""
    import os
    apikey = os.getenv("STOOQ_API_KEY")
    if not apikey:
        return 0
    url = f"https://stooq.com/q/d/l/?s={_stooq_symbol(symbol)}&i=d&apikey={apikey}"
    try:
        r = requests.get(url, timeout=20, headers={"User-Agent": "DK-Investing/0.1 (research)"})
        if r.status_code != 200:
            return 0
        text = r.text.strip()
        # Stooq returns "No data" or HTML on bad symbols
        if not text or text.lower().startswith("<") or "no data" in text.lower():
            return 0
        reader = csv.DictReader(io.StringIO(text))
        rows = []
        for row in reader:
            d = row.get("Date")
            if not d:
                continue
            def _f(key):
                v = row.get(key)
                try:
                    return float(v)
                except (TypeError, ValueError):
                    return None
            rows.append({
                "ts": f"{d}T00:00:00",
                "open": _f("Open"),
                "high": _f("High"),
                "low": _f("Low"),
                "close": _f("Close"),
                "volume": _f("Volume"),
            })
        if not rows:
            return 0
        rows = rows[-max_bars:]  # keep most recent N bars
        return db.upsert_prices(symbol, rows)
    except Exception as e:
        print(f"[stooq] {symbol}: {e}")
        return 0
