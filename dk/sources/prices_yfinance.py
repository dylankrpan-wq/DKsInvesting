from __future__ import annotations
import yfinance as yf
from dk.store import db


def fetch_prices(symbol: str, period: str = "3mo", interval: str = "1d") -> int:
    """Fetch recent OHLCV bars and store. Returns rows written."""
    try:
        t = yf.Ticker(symbol)
        hist = t.history(period=period, interval=interval, auto_adjust=False)
        if hist.empty:
            return 0
        rows = []
        for ts, row in hist.iterrows():
            rows.append({
                "ts": ts.isoformat(),
                "open": float(row["Open"]) if row["Open"] == row["Open"] else None,
                "high": float(row["High"]) if row["High"] == row["High"] else None,
                "low": float(row["Low"]) if row["Low"] == row["Low"] else None,
                "close": float(row["Close"]) if row["Close"] == row["Close"] else None,
                "volume": float(row["Volume"]) if row["Volume"] == row["Volume"] else None,
            })
        return db.upsert_prices(symbol, rows)
    except Exception as e:
        print(f"[yfinance] {symbol}: {e}")
        return 0


def fetch_earnings(symbol: str) -> int:
    """Pull next-earnings date if available."""
    try:
        t = yf.Ticker(symbol)
        cal = t.calendar
        if not cal:
            return 0
        ed = cal.get("Earnings Date")
        if not ed:
            return 0
        # ed can be a list of dates
        date = ed[0] if isinstance(ed, list) else ed
        rows = [{
            "symbol": symbol,
            "report_date": str(date),
            "eps_estimate": cal.get("Earnings Average"),
            "eps_actual": None,
            "revenue_estimate": cal.get("Revenue Average"),
            "revenue_actual": None,
        }]
        return db.upsert_earnings(rows)
    except Exception as e:
        print(f"[yf earnings] {symbol}: {e}")
        return 0
