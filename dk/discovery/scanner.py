"""Discovery scanner — finds fresh, high-potential candidates outside the watchlist.

Sources:
  1. Ticker mentions extracted from news headlines we already store.
     Pattern: $TICKER, (NYSE: TICKER), (NASDAQ: TICKER), or standalone caps.
     Filtered against a false-positive denylist + validated via yfinance.
  2. Recent SEC EDGAR S-1 filings (already in `ipos` table).
  3. Manually added via `mark_candidate(sym)`.

Each candidate is validated (real ticker, market cap > $200M, regular-market price > $1),
prices backfilled (3 months), then run through the existing opportunity scorer.
"""
from __future__ import annotations
import re
import sqlite3
import time
from datetime import datetime, timedelta
import yfinance as yf
from dk.config import DB_PATH, equity_symbols
from dk.store import db as store
from dk.sources import prices_yfinance
from dk.opportunity.score import score_symbol


# -- Ticker extraction --

# $TSLA / (NYSE: TSLA) / (NASDAQ: TSLA) / standalone uppercase 2-5 letters
TICKER_PATTERNS = [
    re.compile(r'\$([A-Z]{1,5})\b'),                                  # $TSLA
    re.compile(r'\((?:NYSE|NASDAQ|AMEX)\s*:\s*([A-Z]{1,5})\)'),       # (NYSE: TSLA)
    re.compile(r'\b([A-Z]{2,5})\b'),                                  # standalone
]

# Words that look like tickers but are noise. Aggressive denylist.
FALSE_POSITIVES = {
    # generic English / business jargon
    "THE","AND","FOR","ARE","BUT","NOT","YOU","ALL","CAN","HER","WAS","ONE","OUR","OUT",
    "DAY","GET","HAS","HIM","HIS","HOW","NEW","NOW","OLD","SEE","TWO","WAY","WHO","BOY",
    "DID","ITS","LET","PUT","SAY","SHE","TOO","USE","BIG","TOP","END","FAR","TRY","TEN",
    "GOT","WIN","LOW","HIGH","UP","DOWN","NEXT","LAST","WILL","JUST","MORE","MOST",
    "ONLY","OVER","SOME","SUCH","THAN","THAT","THEM","THEN","THIS","WERE","WHEN","WITH",
    "INTO","GOOD","BEST","YEAR","WEEK","MUCH","MANY","LONG","TIME","WHAT","BACK","CALL",
    "DEAL","FIRM","FROM","HIGH","LIFE","MAKE","NEED","NEWS","PART","RATE","RISE","RISK",
    "SAID","SEEN","SIDE","SOLD","TELL","TOLD","TURN","WANT","KEEP","LEAD","LATE","WORK",
    "YEARS","BANK","FUND","RATES","STOCK","GAINS","LOSS","LOW","SAYS","FIRMS","SECTOR",
    "MARKET","SHARES","STOCKS","RECORD","PROFIT","SECTOR","REPORT","EARNINGS","REVENUE",
    "GROWTH","DEMAND","SUPPLY","INVESTORS","ANALYSTS","INDEX","FUTURES","OPTIONS","DIVIDEND",
    # finance acronyms
    "CEO","CFO","COO","CTO","CIO","CMO","SEC","IPO","CPI","NFP","FED","FOMC","ECB","BOE",
    "GDP","ETF","ESG","WSJ","CNBC","CNN","BBC","FOX","FT","FY","Q1","Q2","Q3","Q4","H1","H2",
    "PE","PB","PEG","ROI","ROE","ROA","EPS","EBIT","EBITDA","DCF","IRR","NAV","USD","EUR",
    "GBP","JPY","CNY","BRL","INR","RUB","KRW","HKD","CAD","AUD","CHF",
    # geos / orgs
    "USA","UK","EU","UN","NYC","LA","SF","DC","NATO","OPEC","ASEAN",
    # tech / AI
    "AI","ML","API","UI","UX","IT","HR","PR","TV","CD","PC","OS","HD","SSD","CPU","GPU",
    # months / days
    "JAN","FEB","MAR","APR","MAY","JUN","JUL","AUG","SEP","OCT","NOV","DEC",
    "MON","TUE","WED","THU","FRI","SAT","SUN",
    # common stop-tickers that resolve in yfinance but aren't useful
    "PM","AM","ET","PT","CT","MT","BST","UTC","GMT",
}


def _extract_from_text(text: str) -> dict[str, int]:
    if not text:
        return {}
    counts: dict[str, int] = {}
    for pat in TICKER_PATTERNS:
        for m in pat.findall(text):
            sym = m.upper()
            if sym in FALSE_POSITIVES:
                continue
            counts[sym] = counts.get(sym, 0) + 1
    return counts


def _candidates_from_news(min_mentions: int = 3, lookback_hours: int = 72) -> dict[str, int]:
    cutoff = (datetime.utcnow() - timedelta(hours=lookback_hours)).isoformat()
    with sqlite3.connect(DB_PATH) as c:
        rows = c.execute(
            "SELECT title, summary FROM news WHERE fetched_at >= ?",
            (cutoff,),
        ).fetchall()
    totals: dict[str, int] = {}
    for title, summary in rows:
        merged = ((title or "") + " " + (summary or "")).strip()
        # Be strict: only use $TICKER and (EXCH: TICKER) patterns to avoid noise.
        # The plain-CAPS pattern is too noisy for un-validated candidates.
        for pat in TICKER_PATTERNS[:2]:
            for m in pat.findall(merged):
                sym = m.upper()
                if sym in FALSE_POSITIVES:
                    continue
                totals[sym] = totals.get(sym, 0) + 1
        # Add caps tokens with stricter requirement: must appear in title (signal-rich)
        for m in TICKER_PATTERNS[2].findall(title or ""):
            sym = m.upper()
            if sym in FALSE_POSITIVES:
                continue
            totals[sym] = totals.get(sym, 0) + 1
    return {s: n for s, n in totals.items() if n >= min_mentions}


def _candidates_from_ipos() -> list[str]:
    """Pull recent S-1 filings; we don't always know the proposed ticker but we
    surface them as named candidates for manual review."""
    cutoff = (datetime.utcnow() - timedelta(days=14)).date().isoformat()
    with sqlite3.connect(DB_PATH) as c:
        rows = c.execute(
            "SELECT name FROM ipos WHERE expected_date >= ? AND symbol IS NULL",
            (cutoff,),
        ).fetchall()
    # IPO candidates with no ticker yet — return as informational only
    return [r[0] for r in rows if r[0]]


def _validate(symbol: str) -> dict | None:
    """Use yfinance to validate. Returns enriched dict or None if invalid."""
    try:
        t = yf.Ticker(symbol)
        info = t.fast_info  # quick path; doesn't always have everything
        price = float(getattr(info, "last_price", 0) or 0)
        mcap = float(getattr(info, "market_cap", 0) or 0)
        if price < 1.0 or mcap < 200_000_000:
            return None
        # Try richer .info for name/sector (best-effort)
        name, sector = symbol, "?"
        try:
            full = t.info or {}
            name = full.get("shortName") or full.get("longName") or symbol
            sector = full.get("sector") or "?"
        except Exception:
            pass
        return {
            "symbol": symbol,
            "name": name,
            "sector": sector,
            "market_cap": mcap,
            "last_price": price,
        }
    except Exception:
        return None


def scan(min_mentions: int = 3, max_validate: int = 25) -> dict:
    """Run the full discovery pipeline. Returns a summary dict."""
    excluded = set(equity_symbols())
    raw_mentions = _candidates_from_news(min_mentions=min_mentions)
    # Drop tickers already on watchlist
    raw_mentions = {s: n for s, n in raw_mentions.items() if s not in excluded}
    # Sort by mention count desc; cap how many we validate (yfinance is rate-limited)
    sorted_mentions = sorted(raw_mentions.items(), key=lambda x: x[1], reverse=True)[:max_validate]

    accepted: list[dict] = []
    rejected: int = 0
    for sym, count in sorted_mentions:
        v = _validate(sym)
        time.sleep(0.3)  # courtesy
        if not v:
            rejected += 1
            continue
        # Backfill prices so the opportunity scorer has data
        prices_yfinance.fetch_prices(sym)

        # Score it
        with sqlite3.connect(DB_PATH) as c:
            try:
                s = score_symbol(c, sym)
                v["score"] = s.score
                v["score_direction"] = s.direction
            except Exception:
                v["score"] = 0
                v["score_direction"] = "?"
        v["mention_count"] = count
        v["discovered_via"] = "news_mentions"
        v["notes"] = f"{count} mentions in last 72h news"
        accepted.append(v)

    if accepted:
        store.upsert_candidates(accepted)

    return {
        "raw_count": len(raw_mentions),
        "validated": len(accepted),
        "rejected": rejected,
        "top_3": [{"symbol": a["symbol"], "score": a["score"], "mentions": a["mention_count"]}
                  for a in sorted(accepted, key=lambda x: x["score"], reverse=True)[:3]],
        "ipo_pipeline_count": len(_candidates_from_ipos()),
    }


def list_candidates(min_score: float = 0.0) -> list[dict]:
    with sqlite3.connect(DB_PATH) as c:
        c.row_factory = sqlite3.Row
        rows = c.execute(
            """SELECT symbol, name, sector, market_cap, last_price, mention_count,
                      discovered_via, score, score_direction, notes, first_seen, last_seen
               FROM candidates WHERE score >= ?
               ORDER BY score DESC""",
            (min_score,),
        ).fetchall()
        return [dict(r) for r in rows]
