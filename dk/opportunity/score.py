"""Opportunity score — composite ranking signal.

Frame: this is "pay attention to this name" — NOT a buy/sell signal.

Components (each clipped to [-1, 1] then weighted):
  PRICE_MOM  (0.25)  blended 1d / 5d / 20d return, normalized vs ticker's own vol
  VOL_MOM    (0.15)  latest volume vs trailing 20d avg, log-scaled
  NEWS_VEL   (0.15)  count of news in 24h vs 7d-trailing-avg per-day count
  SENTIMENT  (0.30)  weighted avg sentiment over last 24h (recency-weighted)
  EARN_PROX  (0.15)  proximity boost if earnings within 7 days (linear)

Final score is rescaled to 0-100 for display. Direction (bull/bear) is the
sign of (PRICE_MOM + SENTIMENT) — we surface both magnitude and direction.
"""
from __future__ import annotations
import math
import sqlite3
from dataclasses import dataclass, asdict
from datetime import date, datetime, timezone
from dk.config import DB_PATH, load_watchlist


WEIGHTS = {
    "price_mom": 0.25,
    "vol_mom":   0.15,
    "news_vel":  0.15,
    "sentiment": 0.30,
    "earn_prox": 0.15,
}


def _clip(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def _safe_div(a, b):
    return a / b if b not in (None, 0) else 0.0


@dataclass
class Score:
    symbol: str
    score: float          # 0-100
    direction: str        # "bull" / "bear" / "flat"
    price_mom: float
    vol_mom: float
    news_vel: float
    sentiment: float
    earn_prox: float
    headline_count_24h: int
    next_earnings: str | None


def _price_components(c, sym: str) -> tuple[float, float]:
    rows = c.execute(
        "SELECT close, volume FROM prices WHERE symbol=? ORDER BY ts DESC LIMIT 25",
        (sym,),
    ).fetchall()
    if len(rows) < 6:
        return 0.0, 0.0
    closes = [r[0] for r in rows if r[0]]
    if len(closes) < 6:
        return 0.0, 0.0
    latest = closes[0]
    r1 = _safe_div(latest - closes[1], closes[1])
    r5 = _safe_div(latest - closes[min(5, len(closes) - 1)], closes[min(5, len(closes) - 1)])
    r20 = _safe_div(latest - closes[-1], closes[-1])

    # Daily-return std as a vol denominator
    diffs = [(closes[i] - closes[i + 1]) / closes[i + 1] for i in range(len(closes) - 1)]
    mean = sum(diffs) / len(diffs)
    var = sum((d - mean) ** 2 for d in diffs) / len(diffs)
    std = math.sqrt(var) or 0.01

    # Blend with more weight on 5d (medium-term momentum signal)
    blended = 0.5 * r1 + 0.3 * r5 + 0.2 * r20
    price_mom = _clip(blended / (std * 4))  # 4-sigma → 1.0

    vols = [r[1] for r in rows[1:] if r[1]]
    latest_v = rows[0][1]
    if not vols or not latest_v:
        return price_mom, 0.0
    avg_v = sum(vols) / len(vols)
    if avg_v <= 0:
        return price_mom, 0.0
    # log ratio: 1x → 0, 2x → 0.5, 4x → 1.0
    vol_mom = _clip(math.log2(latest_v / avg_v) / 2.0)
    return price_mom, vol_mom


def _news_components(c, sym: str) -> tuple[float, float, int]:
    """Returns (news_velocity, sentiment_weighted, count_24h)."""
    rows = c.execute(
        """SELECT published, fetched_at, sentiment FROM news
           WHERE symbol=? AND fetched_at >= datetime('now', '-7 days')""",
        (sym,),
    ).fetchall()
    if not rows:
        return 0.0, 0.0, 0
    cutoff_24h = datetime.now(timezone.utc).replace(tzinfo=None)  # approximate
    # Bucket by 'fetched_at' (UTC stored as text)
    last24 = []
    last7 = []
    for pub, fetched, s in rows:
        try:
            t = datetime.fromisoformat(fetched.replace("Z", ""))
        except Exception:
            continue
        last7.append((t, s))
        age_h = (datetime.utcnow() - t).total_seconds() / 3600
        if age_h <= 24:
            last24.append((t, s, age_h))

    count_24h = len(last24)
    avg_per_day_7d = len(last7) / 7
    # velocity: 1 SD-ish bump if 24h count is 2x baseline; clip
    if avg_per_day_7d > 0:
        velocity = _clip((count_24h - avg_per_day_7d) / max(avg_per_day_7d, 1.0))
    else:
        velocity = _clip(count_24h / 3)

    # Recency-weighted sentiment over last 24h (newer = higher weight)
    if last24:
        weights = [max(0.1, 1.0 - h / 24) for _, _, h in last24]
        scores = [s if s is not None else 0.0 for _, s, _ in last24]
        wsum = sum(weights)
        sentiment = sum(s * w for s, w in zip(scores, weights)) / wsum if wsum else 0.0
    else:
        # fall back to 7d simple avg
        scored = [s for _, s in last7 if s is not None]
        sentiment = (sum(scored) / len(scored)) if scored else 0.0

    return velocity, _clip(sentiment), count_24h


def _earnings_proximity(c, sym: str) -> tuple[float, str | None]:
    row = c.execute(
        "SELECT report_date FROM earnings WHERE symbol=? AND report_date >= date('now') ORDER BY report_date ASC LIMIT 1",
        (sym,),
    ).fetchone()
    if not row:
        return 0.0, None
    rd = row[0]
    try:
        d = date.fromisoformat(rd[:10])
    except Exception:
        return 0.0, rd
    days_out = (d - date.today()).days
    if days_out < 0:
        return 0.0, rd
    if days_out <= 7:
        prox = 1.0 - (days_out / 7.0)  # 1.0 today → ~0 at day 7
    elif days_out <= 30:
        prox = 0.3 * (1.0 - (days_out - 7) / 23.0)
    else:
        prox = 0.0
    return _clip(prox), rd


def score_symbol(c, sym: str) -> Score:
    pm, vm = _price_components(c, sym)
    nv, sent, n24 = _news_components(c, sym)
    ep, next_er = _earnings_proximity(c, sym)

    raw = (
        WEIGHTS["price_mom"] * pm
        + WEIGHTS["vol_mom"] * vm
        + WEIGHTS["news_vel"] * nv
        + WEIGHTS["sentiment"] * sent
        + WEIGHTS["earn_prox"] * ep
    )
    # Earn_prox always positive; magnitude uses |raw|, direction uses sign of (pm + sent)
    score_100 = round(abs(raw) * 100, 1)
    direction = "bull" if (pm + sent) > 0.05 else ("bear" if (pm + sent) < -0.05 else "flat")
    return Score(
        symbol=sym,
        score=min(score_100, 100.0),
        direction=direction,
        price_mom=round(pm, 3),
        vol_mom=round(vm, 3),
        news_vel=round(nv, 3),
        sentiment=round(sent, 3),
        earn_prox=round(ep, 3),
        headline_count_24h=n24,
        next_earnings=next_er,
    )


def rank_all() -> list[dict]:
    wl = load_watchlist()
    syms = [e["symbol"] for e in (wl.get("equities") or []) + (wl.get("etfs") or [])]
    out: list[Score] = []
    with sqlite3.connect(DB_PATH) as c:
        for s in syms:
            try:
                out.append(score_symbol(c, s))
            except Exception as e:
                print(f"[score] {s}: {e}")
    out.sort(key=lambda r: r.score, reverse=True)
    return [asdict(r) for r in out]


if __name__ == "__main__":
    import json
    print(json.dumps(rank_all(), indent=2, default=str))
