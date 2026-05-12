"""Market-wide sentiment / "Fear & Greed"–style composite.

Combines free signals available from yfinance + our own DB:
  1. **VIX regime** — high VIX = fear (inverted to 0-100)
  2. **Safe haven demand** — TLT (long bonds) outperforming SPY = fear
  3. **Junk bond demand** — HYG vs LQD spread = risk-on/risk-off
  4. **Stock momentum** — SPY vs its 125-day MA
  5. **Market breadth** — share of watchlist names above their 50-day SMA
  6. **News breadth** — share of recent articles with positive vs negative sentiment

Each component is normalized 0-100 then averaged.
Result: composite 0 = extreme fear, 100 = extreme greed.
"""
from __future__ import annotations
import sqlite3
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
import numpy as np
import pandas as pd
import yfinance as yf
from dk.config import DB_PATH, equity_symbols


@dataclass
class MarketSentiment:
    composite: float = 50.0
    label: str = "Neutral"
    components: dict | None = None
    fetched_at: str = ""

    def to_dict(self):
        d = asdict(self)
        d["components"] = self.components or {}
        return d


def _label_for(score: float) -> str:
    if score >= 80: return "Extreme Greed"
    if score >= 60: return "Greed"
    if score >= 40: return "Neutral"
    if score >= 20: return "Fear"
    return "Extreme Fear"


def _safe_history(ticker: str, period: str = "6mo") -> pd.DataFrame:
    try:
        return yf.Ticker(ticker).history(period=period, interval="1d", auto_adjust=False)
    except Exception:
        return pd.DataFrame()


def _vix_score() -> float | None:
    df = _safe_history("^VIX", "1y")
    if df.empty:
        return None
    latest = float(df["Close"].iloc[-1])
    # Map VIX 10-40 → greed 100 → fear 0 (inverted)
    score = max(0, min(100, (40.0 - latest) / 30.0 * 100.0))
    return score


def _safe_haven() -> float | None:
    spy = _safe_history("SPY", "6mo")
    tlt = _safe_history("TLT", "6mo")
    if spy.empty or tlt.empty:
        return None
    # 20-day relative performance: SPY % chg minus TLT % chg
    spy_ret = (spy["Close"].iloc[-1] / spy["Close"].iloc[-21] - 1) * 100
    tlt_ret = (tlt["Close"].iloc[-1] / tlt["Close"].iloc[-21] - 1) * 100
    spread = spy_ret - tlt_ret
    # +10% spread = greed 100, -10% spread = fear 0
    score = max(0, min(100, (spread + 10.0) / 20.0 * 100.0))
    return score


def _junk_demand() -> float | None:
    hyg = _safe_history("HYG", "3mo")
    lqd = _safe_history("LQD", "3mo")
    if hyg.empty or lqd.empty:
        return None
    hyg_ret = (hyg["Close"].iloc[-1] / hyg["Close"].iloc[-21] - 1) * 100
    lqd_ret = (lqd["Close"].iloc[-1] / lqd["Close"].iloc[-21] - 1) * 100
    spread = hyg_ret - lqd_ret
    # +3% = greed 100, -3% = fear 0
    score = max(0, min(100, (spread + 3.0) / 6.0 * 100.0))
    return score


def _spy_momentum() -> float | None:
    spy = _safe_history("SPY", "1y")
    if spy.empty or len(spy) < 130:
        return None
    last = float(spy["Close"].iloc[-1])
    ma125 = float(spy["Close"].iloc[-125:].mean())
    diff_pct = (last - ma125) / ma125 * 100
    # +10% = greed 100, -10% = fear 0
    score = max(0, min(100, (diff_pct + 10.0) / 20.0 * 100.0))
    return score


def _breadth_from_watchlist() -> float | None:
    """% of watchlist names trading above their 50-day SMA — proxy for market breadth."""
    syms = equity_symbols()
    if not syms:
        return None
    above = 0
    counted = 0
    with sqlite3.connect(DB_PATH) as c:
        for sym in syms:
            rows = c.execute(
                "SELECT close FROM prices WHERE symbol=? ORDER BY ts DESC LIMIT 50",
                (sym,),
            ).fetchall()
            if len(rows) < 50:
                continue
            closes = np.array([r[0] for r in rows if r[0] is not None], dtype=float)
            if len(closes) < 50:
                continue
            sma50 = closes.mean()
            if closes[0] > sma50:
                above += 1
            counted += 1
    if not counted:
        return None
    pct = above / counted * 100
    return pct


def _news_breadth() -> float | None:
    with sqlite3.connect(DB_PATH) as c:
        rows = c.execute(
            """SELECT sentiment FROM news
               WHERE sentiment IS NOT NULL
                 AND fetched_at >= datetime('now', '-1 day')"""
        ).fetchall()
    if not rows:
        return None
    scores = [r[0] for r in rows]
    pos = sum(1 for s in scores if s > 0.05)
    neg = sum(1 for s in scores if s < -0.05)
    total = pos + neg
    if not total:
        return 50.0
    pct_pos = pos / total * 100
    return pct_pos


def compute() -> MarketSentiment:
    components = {
        "vix": _vix_score(),
        "safe_haven": _safe_haven(),
        "junk_demand": _junk_demand(),
        "spy_momentum": _spy_momentum(),
        "breadth_watchlist": _breadth_from_watchlist(),
        "news_breadth_24h": _news_breadth(),
    }
    valid = [v for v in components.values() if v is not None]
    if not valid:
        return MarketSentiment(composite=50.0, label="Unknown", components=components,
                                fetched_at=datetime.now(timezone.utc).isoformat())
    composite = sum(valid) / len(valid)
    return MarketSentiment(
        composite=round(composite, 1),
        label=_label_for(composite),
        components=components,
        fetched_at=datetime.now(timezone.utc).isoformat(),
    )


def persist_snapshot() -> dict:
    """Compute + save a snapshot to DB. Returns the snapshot."""
    snap = compute()
    with sqlite3.connect(DB_PATH) as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS market_sentiment (
                snapshot_ts TEXT PRIMARY KEY,
                composite REAL,
                label TEXT,
                components_json TEXT
            )
        """)
        import json
        c.execute(
            "INSERT OR REPLACE INTO market_sentiment (snapshot_ts, composite, label, components_json) VALUES (?, ?, ?, ?)",
            (snap.fetched_at, snap.composite, snap.label, json.dumps(snap.components)),
        )
        c.commit()
    return snap.to_dict()


def history(days: int = 30) -> pd.DataFrame:
    with sqlite3.connect(DB_PATH) as c:
        c.execute("""CREATE TABLE IF NOT EXISTS market_sentiment (
                       snapshot_ts TEXT PRIMARY KEY, composite REAL, label TEXT,
                       components_json TEXT)""")
        return pd.read_sql_query(
            f"""SELECT snapshot_ts, composite, label FROM market_sentiment
                WHERE snapshot_ts >= datetime('now', '-{int(days)} days')
                ORDER BY snapshot_ts ASC""",
            c,
        )
