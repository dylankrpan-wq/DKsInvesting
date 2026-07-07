"""Market-wide snapshot: index levels + sector rotation.

The 'state of the market as a whole' — the four major indices and the 11 GICS
sector SPDRs ranked best→worst so you see leadership/rotation at a glance. Uses
the Yahoo v8 chart endpoint (datacenter-friendly, same as the leaderboards) and
fetches them in parallel.
"""
from __future__ import annotations
import concurrent.futures
from dk.sources.leaderboards import _chart_quote

INDICES = [
    ("^GSPC", "S&P 500"), ("^IXIC", "Nasdaq"),
    ("^DJI", "Dow"), ("^RUT", "Russell 2000"),
]

SECTORS = [
    ("XLK", "Technology"), ("XLC", "Communications"), ("XLY", "Cons. Discretionary"),
    ("XLP", "Cons. Staples"), ("XLE", "Energy"), ("XLF", "Financials"),
    ("XLV", "Health Care"), ("XLI", "Industrials"), ("XLB", "Materials"),
    ("XLRE", "Real Estate"), ("XLU", "Utilities"),
]


def _fetch(pairs: list[tuple[str, str]]) -> list[dict]:
    syms = [s for s, _ in pairs]
    names = dict(pairs)
    out = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
        for sym, q in zip(syms, ex.map(_chart_quote, syms)):
            if q.get("price") is not None or q.get("change_pct") is not None:
                out.append({"symbol": sym, "name": names[sym],
                            "price": q.get("price"), "change_pct": q.get("change_pct")})
    return out


def indices() -> list[dict]:
    return _fetch(INDICES)


def sectors() -> list[dict]:
    out = _fetch(SECTORS)
    out.sort(key=lambda x: (x.get("change_pct") if x.get("change_pct") is not None else -99),
             reverse=True)
    return out
