"""Sentiment-based indicators per ticker."""
from __future__ import annotations
import sqlite3
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
import numpy as np
from dk.config import DB_PATH


@dataclass
class SentimentSnapshot:
    symbol: str
    avg_24h: float | None = None
    avg_7d: float | None = None
    slope_7d: float | None = None        # linear-regression slope of daily-avg sentiment
    momentum: float | None = None        # avg_24h - avg_prior_6d
    article_count_24h: int = 0
    article_baseline_per_day: float | None = None
    velocity: float | None = None        # 24h count / baseline
    bull_pct: float | None = None        # share of articles >  0.05
    bear_pct: float | None = None        # share of articles < -0.05
    unique_sources_7d: int = 0
    top_bull: dict | None = None         # most-positive recent article (title, url, score)
    top_bear: dict | None = None         # most-negative recent article

    def to_dict(self):
        return asdict(self)


def compute(symbol: str) -> SentimentSnapshot:
    snap = SentimentSnapshot(symbol=symbol)
    now = datetime.utcnow()
    cutoff_7d = (now - timedelta(days=7)).isoformat()
    cutoff_24h = (now - timedelta(hours=24)).isoformat()
    with sqlite3.connect(DB_PATH) as c:
        c.row_factory = sqlite3.Row
        rows = c.execute(
            """SELECT title, url, source, sentiment, fetched_at
               FROM news WHERE symbol=? AND fetched_at >= ? AND sentiment IS NOT NULL""",
            (symbol, cutoff_7d),
        ).fetchall()

    if not rows:
        return snap

    scores_7d = [r["sentiment"] for r in rows]
    snap.avg_7d = float(np.mean(scores_7d))

    # 24h subset
    last24 = [r for r in rows if r["fetched_at"] >= cutoff_24h]
    if last24:
        snap.avg_24h = float(np.mean([r["sentiment"] for r in last24]))
    snap.article_count_24h = len(last24)

    # Daily averages over 7 days for slope
    daily = {}
    for r in rows:
        try:
            d = r["fetched_at"][:10]
        except Exception:
            continue
        daily.setdefault(d, []).append(r["sentiment"])
    if len(daily) >= 3:
        days_sorted = sorted(daily.keys())
        ys = np.array([np.mean(daily[d]) for d in days_sorted], dtype=float)
        xs = np.arange(len(ys), dtype=float)
        try:
            slope = float(np.polyfit(xs, ys, 1)[0])
            snap.slope_7d = slope
        except Exception:
            pass

    # Momentum: 24h vs prior 6 days
    prior6 = [r["sentiment"] for r in rows if r["fetched_at"] < cutoff_24h]
    if last24 and prior6:
        snap.momentum = float(np.mean([r["sentiment"] for r in last24]) - np.mean(prior6))

    # Article velocity
    days_seen = max(1, len(daily))
    snap.article_baseline_per_day = len(rows) / 7.0
    if snap.article_baseline_per_day:
        snap.velocity = snap.article_count_24h / snap.article_baseline_per_day

    # Bull / bear breadth
    pos = sum(1 for s in scores_7d if s > 0.05)
    neg = sum(1 for s in scores_7d if s < -0.05)
    n = len(scores_7d)
    snap.bull_pct = pos / n * 100.0
    snap.bear_pct = neg / n * 100.0

    # Unique sources
    snap.unique_sources_7d = len({r["source"] for r in rows if r["source"]})

    # Top bull/bear articles in 7d
    sorted_pos = sorted([r for r in rows if r["sentiment"] is not None and r["sentiment"] > 0],
                        key=lambda r: r["sentiment"], reverse=True)
    sorted_neg = sorted([r for r in rows if r["sentiment"] is not None and r["sentiment"] < 0],
                        key=lambda r: r["sentiment"])
    if sorted_pos:
        snap.top_bull = {"title": sorted_pos[0]["title"], "url": sorted_pos[0]["url"],
                         "score": sorted_pos[0]["sentiment"], "source": sorted_pos[0]["source"]}
    if sorted_neg:
        snap.top_bear = {"title": sorted_neg[0]["title"], "url": sorted_neg[0]["url"],
                         "score": sorted_neg[0]["sentiment"], "source": sorted_neg[0]["source"]}
    return snap
