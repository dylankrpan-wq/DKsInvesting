"""Shared research-link builders so every reported item can link to its source.

Keeps URL construction in one place (per the standing 'always link the data'
directive) — used by the dashboard drill-downs and the Telegram digests.
"""
from __future__ import annotations
from urllib.parse import quote_plus


def yahoo(symbol: str) -> str:
    return f"https://finance.yahoo.com/quote/{symbol}"


def tradingview(symbol: str) -> str:
    return f"https://www.tradingview.com/symbols/{symbol}/"


def finviz(symbol: str) -> str:
    return f"https://finviz.com/quote.ashx?t={symbol}"


def sec_edgar(symbol: str) -> str:
    return ("https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany"
            f"&ticker={symbol}&type=&dateb=&owner=include&count=40")


def stocktwits(symbol: str) -> str:
    return f"https://stocktwits.com/symbol/{symbol}"


def google_news(symbol: str, name: str | None = None) -> str:
    q = f"{name} {symbol} stock" if name else f"{symbol} stock"
    return f"https://news.google.com/search?q={quote_plus(q)}"


def coingecko(name_or_id: str) -> str:
    return f"https://www.coingecko.com/en/coins/{quote_plus((name_or_id or '').lower().replace(' ', '-'))}"


def research_set(symbol: str, name: str | None = None) -> dict[str, str]:
    """All the standard research links for an equity symbol."""
    return {
        "Chart (TradingView)": tradingview(symbol),
        "Yahoo Finance": yahoo(symbol),
        "Finviz": finviz(symbol),
        "SEC filings": sec_edgar(symbol),
        "News": google_news(symbol, name),
        "StockTwits": stocktwits(symbol),
    }
