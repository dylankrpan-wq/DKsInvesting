"""TradingView Technical Ratings scraper.

Uses the unofficial-but-stable `tradingview-ta` library which calls
TradingView's public TA scanner endpoint. No authentication required.

Returns the recommendation summary (STRONG_BUY/BUY/NEUTRAL/SELL/STRONG_SELL)
across multiple intervals + the underlying signal counts.
"""
from __future__ import annotations
import time
from dk.config import equity_symbols
from dk.store import db


# yfinance ticker → TradingView (exchange, screener) hint.
# For most US equities NASDAQ guesses correctly; we fall back to NYSE if needed.
EXCHANGE_HINTS = {
    "AAPL": "NASDAQ", "MSFT": "NASDAQ", "NVDA": "NASDAQ", "AMD": "NASDAQ",
    "INTC": "NASDAQ", "MU": "NASDAQ", "HOOD": "NASDAQ", "ASTS": "NASDAQ",
    "SPT": "NASDAQ", "RR": "NASDAQ", "DRAM": "NASDAQ",
    "QQQ": "NASDAQ", "VOO": "AMEX", "IBIT": "NASDAQ", "ETHE": "AMEX",
    "GOOGL": "NASDAQ", "MP": "NYSE", "RBC": "NYSE", "BKH": "NYSE",
}

INTERVAL_MAP = {
    "1h": "INTERVAL_1_HOUR",
    "1d": "INTERVAL_1_DAY",
    "1W": "INTERVAL_1_WEEK",
}


def _fetch_one(symbol: str, exchange: str, interval_label: str, ta_module) -> dict | None:
    interval_const = getattr(ta_module.Interval, INTERVAL_MAP[interval_label])
    try:
        handler = ta_module.TA_Handler(
            symbol=symbol, exchange=exchange,
            screener="america", interval=interval_const, timeout=10,
        )
        result = handler.get_analysis()
    except Exception as e:
        msg = str(e)
        # tradingview-ta raises if symbol/exchange combo doesn't exist; try NYSE fallback
        if "Exchange or symbol not found" in msg and exchange == "NASDAQ":
            try:
                handler = ta_module.TA_Handler(
                    symbol=symbol, exchange="NYSE",
                    screener="america", interval=interval_const, timeout=10,
                )
                result = handler.get_analysis()
            except Exception:
                return None
        else:
            return None

    s = result.summary or {}
    osc = result.oscillators or {}
    indicators = result.indicators or {}
    return {
        "symbol": symbol,
        "interval": interval_label,
        "recommendation": s.get("RECOMMENDATION"),
        "buy_signals": s.get("BUY"),
        "sell_signals": s.get("SELL"),
        "neutral_signals": s.get("NEUTRAL"),
        "rsi": indicators.get("RSI"),
        "macd_hist": indicators.get("MACD.macd"),
    }


def fetch_for_watchlist(intervals: list[str] | None = None) -> int:
    intervals = intervals or ["1d"]
    try:
        from tradingview_ta import TA_Handler, Interval  # noqa: F401
        import tradingview_ta as ta
    except ImportError:
        print("[tradingview-ta] not installed; skipping. uv add tradingview-ta")
        return 0

    rows: list[dict] = []
    for sym in equity_symbols():
        exchange = EXCHANGE_HINTS.get(sym, "NASDAQ")
        for iv in intervals:
            r = _fetch_one(sym, exchange, iv, ta)
            if r:
                rows.append(r)
            time.sleep(0.25)
    return db.upsert_tv_ratings(rows)


def fetch_for_symbol(symbol: str, intervals: list[str] | None = None) -> int:
    intervals = intervals or ["1d"]
    try:
        import tradingview_ta as ta
    except ImportError:
        return 0
    exchange = EXCHANGE_HINTS.get(symbol, "NASDAQ")
    rows = []
    for iv in intervals:
        r = _fetch_one(symbol, exchange, iv, ta)
        if r:
            rows.append(r)
    return db.upsert_tv_ratings(rows)
