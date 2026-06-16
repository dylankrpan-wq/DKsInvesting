"""Pull market-context indicators (DXY, VIX, 10Y, WTI, gold)."""
from __future__ import annotations
import yfinance as yf
from dk.store import db

# (yf_symbol, internal_symbol, label)
INSTRUMENTS = [
    ("^VIX", "VIX", "VIX (vol)"),
    ("^TNX", "US10Y", "US 10Y yield"),
    ("DX-Y.NYB", "DXY", "Dollar index"),
    ("CL=F", "WTI", "WTI crude"),
    ("GC=F", "GOLD", "Gold futures"),
    ("^GSPC", "SPX", "S&P 500"),
]


def fetch_all() -> int:
    rows = []
    for yf_sym, sym, label in INSTRUMENTS:
        try:
            t = yf.Ticker(yf_sym)
            hist = t.history(period="5d", interval="1d")
            if hist.empty or len(hist) < 2:
                continue
            last = float(hist["Close"].iloc[-1])
            prev = float(hist["Close"].iloc[-2])
            if last != last or prev != prev:  # NaN (incomplete/glitched bar) — skip, don't store None
                continue
            chg = (last - prev) / prev * 100 if prev else 0.0
            rows.append({
                "symbol": sym, "label": label,
                "last_value": last, "chg_pct": chg,
            })
        except Exception as e:
            print(f"[macro_context] {yf_sym}: {e}")
    if not rows:
        return 0
    from dk.store.db import conn
    with conn() as c:
        c.executemany("""
            INSERT OR REPLACE INTO macro_context
              (symbol, label, last_value, chg_pct, fetched_at)
            VALUES (:symbol, :label, :last_value, :chg_pct, CURRENT_TIMESTAMP)
        """, rows)
    return len(rows)
