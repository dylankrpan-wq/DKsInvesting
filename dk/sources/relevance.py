"""Relevance gate — only tag an article to a ticker if it's DIRECTLY about it.

Prevents false matches like short tickers ("MU", "T", "ON") hitting random
English words, or vague market-roundup listicles getting attached to a name.

A match requires one of:
  - the cashtag ($SYMBOL) appears
  - the SYMBOL appears as a standalone UPPERCASE word (tickers are written upper),
    so "CAT" (Caterpillar) matches but "cat" the animal does not
  - the company name (cleaned of Inc/Corp/etc.) appears
  - a distinctive (5+ char) leading word of the company name appears
"""
from __future__ import annotations
import re

_SUFFIXES = [
    " incorporated", " inc.", " inc", " corporation", " corp.", " corp",
    " co.", " co", " ltd.", " ltd", " plc", " s.a.", " sa", " ag", " nv",
    " holdings", " holding", " group", " company", " limited",
    " technologies", " technology", " international", " & co",
    " systems", " enterprises", " industries", " trust", " etf", " fund",
    " class a", " class b", " common stock", " depositary",
]

# Short all-caps words that are tickers but also common English/abbreviations —
# require cashtag or name for these to avoid noise.
_AMBIGUOUS = {"ALL", "ARE", "IT", "ON", "OR", "SO", "AI", "GO", "BE", "AM", "PM", "US", "AN"}


def _clean_name(name: str) -> str:
    n = (name or "").lower().strip()
    changed = True
    while changed:
        changed = False
        for s in _SUFFIXES:
            if n.endswith(s):
                n = n[: -len(s)].strip().rstrip(",")
                changed = True
    return n.strip(" ,.")


def is_relevant(symbol: str, name: str | None, title: str, summary: str = "") -> bool:
    raw = f"{title or ''} {summary or ''}".strip()
    if not raw:
        return False
    low = raw.lower()
    sym = (symbol or "").strip()

    # 1) cashtag — always a direct reference
    if sym and f"${sym.lower()}" in low:
        return True

    # 2) SYMBOL as a standalone UPPERCASE token (avoids lowercase word collisions)
    if sym and len(sym) >= 2 and sym.upper() not in _AMBIGUOUS:
        if re.search(rf"(?<![A-Za-z]){re.escape(sym.upper())}(?![A-Za-z0-9])", raw):
            return True

    # 3) cleaned company name as a phrase
    cn = _clean_name(name or "")
    if cn and len(cn) >= 3 and cn in low:
        return True

    # 4) distinctive leading word of the name (e.g. "micron", "nvidia")
    if cn:
        parts = cn.split()
        if parts and len(parts[0]) >= 5 and re.search(rf"\b{re.escape(parts[0])}\b", low):
            return True

    return False


def filter_relevant(symbol: str, name: str | None, rows: list[dict]) -> list[dict]:
    """Keep only rows whose title/summary is directly relevant to symbol/name."""
    return [r for r in rows
            if is_relevant(symbol, name, r.get("title", ""), r.get("summary", ""))]
