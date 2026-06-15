"""Overnight / round-the-clock market context: US index futures + overseas indices.

US cash equities are shut overnight and pre-market, but their *direction* is set
by index futures (ES/NQ/YM/RTY, which trade ~23h) and the Asia/Europe sessions.
yfinance `fast_info` gives last price + previous close in one cheap call per
symbol with no API key, and it updates overnight — confirmed live (ES, NQ, Nikkei
all moving at 1am ET). This feeds the overnight "while you slept" digest, the
morning brief, and the dashboard so the equity side isn't blind overnight.
"""
from __future__ import annotations
import yfinance as yf

# (yf_symbol, internal_symbol, label)
FUTURES = [
    ("ES=F", "ES", "S&P 500 fut"),
    ("NQ=F", "NQ", "Nasdaq 100 fut"),
    ("YM=F", "YM", "Dow fut"),
    ("RTY=F", "RTY", "Russell 2000 fut"),
]

OVERSEAS = [
    ("^N225", "N225", "Nikkei 225"),
    ("^HSI", "HSI", "Hang Seng"),
    ("^GDAXI", "DAX", "DAX (Germany)"),
    ("^FTSE", "FTSE", "FTSE 100"),
]


def _fast_quote(yf_sym: str) -> tuple[float, float] | None:
    """(last_price, previous_close) via yfinance fast_info, or None."""
    try:
        fi = yf.Ticker(yf_sym).fast_info
        # fast_info supports both mapping (.get) and attribute access depending on
        # the yfinance version; try both.
        last = None
        prev = None
        try:
            last = fi.get("lastPrice")
            prev = fi.get("previousClose")
        except Exception:
            pass
        if last is None:
            last = getattr(fi, "last_price", None)
        if prev is None:
            prev = getattr(fi, "previous_close", None)
        if last and prev:
            return float(last), float(prev)
    except Exception as e:
        print(f"[overnight_markets] {yf_sym}: {e}")
    return None


def _fetch(group_items: list[tuple[str, str, str]], group: str) -> list[dict]:
    out = []
    for yf_sym, sym, label in group_items:
        q = _fast_quote(yf_sym)
        if not q:
            continue
        last, prev = q
        out.append({
            "symbol": sym,
            "label": label,
            "group": group,
            "last": round(last, 2),
            "prev_close": round(prev, 2),
            "chg_pct": round((last - prev) / prev * 100, 2) if prev else None,
        })
    return out


def fetch() -> dict:
    """Return {'futures': [...], 'overseas': [...]} with live last/prev/chg_pct."""
    return {"futures": _fetch(FUTURES, "futures"),
            "overseas": _fetch(OVERSEAS, "overseas")}


def format_line(data: dict | None = None) -> str:
    """One compact text block: futures then overseas, arrowed by direction."""
    data = data or fetch()
    def _seg(items):
        bits = []
        for i in items:
            c = i["chg_pct"]
            arrow = "▲" if (c or 0) > 0 else ("▼" if (c or 0) < 0 else "→")
            bits.append(f"{i['symbol']} {arrow}{abs(c):.2f}%" if c is not None else f"{i['symbol']} —")
        return " · ".join(bits)
    parts = []
    if data.get("futures"):
        parts.append("US futures: " + _seg(data["futures"]))
    if data.get("overseas"):
        parts.append("Overseas: " + _seg(data["overseas"]))
    return "\n".join(parts)


if __name__ == "__main__":
    import sys
    try:  # Windows consoles default to cp1252 and choke on ▲/▼ arrows.
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    except Exception:
        pass
    print(format_line())
