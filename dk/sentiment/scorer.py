"""Sentiment scoring for news rows.

Default engine: VADER (fast, no model download, good baseline).
Optional engine: FinBERT (financial-tuned, ~440MB download). Lazy-imported.

Each row gets a `compound` score in [-1, 1]:
  >  0.05  positive
  < -0.05  negative
   else    neutral
"""
from __future__ import annotations
import sqlite3
from dk.config import DB_PATH, load_watchlist
from dk.store import db as store

_VADER = None
_FINBERT = None


def _vader():
    global _VADER
    if _VADER is None:
        from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
        _VADER = SentimentIntensityAnalyzer()
    return _VADER


def _finbert():
    """Lazy-load FinBERT. Requires `transformers` + `torch` (not in default deps)."""
    global _FINBERT
    if _FINBERT is None:
        try:
            from transformers import pipeline
        except ImportError as e:
            raise RuntimeError("FinBERT requires `pip install transformers torch`. "
                               "Stick with engine: vader, or install those deps.") from e
        _FINBERT = pipeline("sentiment-analysis", model="ProsusAI/finbert")
    return _FINBERT


def score_text_vader(text: str) -> float:
    if not text:
        return 0.0
    return _vader().polarity_scores(text)["compound"]


def score_text_finbert(text: str) -> float:
    if not text:
        return 0.0
    out = _finbert()(text[:512])[0]
    label = out["label"].lower()
    score = out["score"]
    if label == "positive":
        return score
    if label == "negative":
        return -score
    return 0.0  # neutral


def score_unscored(limit: int = 1000) -> int:
    """Score any news rows that don't yet have a sentiment value."""
    engine = (load_watchlist().get("sentiment") or {}).get("engine", "vader").lower()
    scorer = score_text_finbert if engine == "finbert" else score_text_vader

    with sqlite3.connect(DB_PATH) as c:
        c.row_factory = sqlite3.Row
        rows = c.execute(
            "SELECT id, title, summary FROM news WHERE sentiment IS NULL LIMIT ?",
            (limit,),
        ).fetchall()
        n = 0
        for r in rows:
            text = (r["title"] or "") + ". " + (r["summary"] or "")
            s = scorer(text)
            c.execute("UPDATE news SET sentiment = ? WHERE id = ?", (s, r["id"]))
            n += 1
        c.commit()
    return n


def label(score: float | None) -> str:
    if score is None:
        return "?"
    if score > 0.05:
        return "+"
    if score < -0.05:
        return "-"
    return "·"
