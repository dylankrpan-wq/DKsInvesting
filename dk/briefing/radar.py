"""Opportunity Radar — the proactive 'what matters now' synthesis layer.

Instead of making the user dig through tables, this reads every signal the
system already captures (alerts, opportunity scores, news, catalysts) and
produces a single PRIORITIZED briefing: what's happening, why it matters,
and what to look at — framed as opportunity discovery, never as trade advice.
"""
from __future__ import annotations
import json
import sqlite3
from datetime import datetime, timezone
from dk.config import DB_PATH, equity_symbols


# alert kind -> (category, icon, why-it-matters template)
KIND_META = {
    "SETUP_SCAN":       ("Setup Scan", "🎯", "A high-R:R defined-risk perp setup the scanner surfaced — tight stop vs target."),
    "THESIS":           ("Stock Thesis", "📋", "A forward-looking thesis on a stock with a setup forming — chart + momentum + catalyst."),
    "CONVICTION_LONG":  ("Conviction", "🎯", "Multiple bullish signals converging hard — the strongest long-side setup the system sees."),
    "CONVICTION_SHORT": ("Conviction", "🎯", "Multiple bearish signals converging hard — the strongest short-side setup the system sees."),
    "HIGH_IMPACT_NEWS": ("Breaking", "⚡", "High-impact headline just dropped — these move stocks fast."),
    "NEWS_VELOCITY":    ("Live Event", "📡", "News volume is spiking — usually means a live event, conference, or developing story."),
    "PERSON_ACTIVITY":  ("Power Player", "📣", "A market-moving figure just spoke or posted — watch for follow-through."),
    "RANK_JUMP":        ("Opportunity", "🚀", "Climbing the opportunity ranking fast — momentum is building."),
    "NEW_TOP":          ("Opportunity", "⭐", "Just broke into the top tier of the watchlist."),
    "SCORE_SURGE":      ("Opportunity", "📈", "Opportunity score jumped sharply since last check."),
    "VOLUME_SPIKE":     ("Unusual Activity", "🔊", "Volume far above normal — someone knows something or a catalyst hit."),
    "PRICE_MOVE":       ("Big Mover", "💥", "Large price move today — worth understanding why."),
    "SENTIMENT_SURGE":  ("Sentiment Shift", "🗞️", "News tone shifted hard — narrative may be changing."),
    "EARNINGS_NEAR":    ("Catalyst Ahead", "📅", "Earnings imminent — expect a volatility event."),
    "EVENT_NEAR":       ("Catalyst Ahead", "📣", "A known market event is imminent."),
    "MACRO_NEAR":       ("Macro", "🌐", "Macro event that can move the whole market."),
    "CRYPTO_MOVE":      ("Crypto Mover", "🪙", "Notable crypto move in the last 24h."),
    "CRYPTO_SPIKE":     ("Crypto Spike", "🚨", "A derivatives pair just spiked hard in minutes — fast, often short-lived."),
    "CUSTOM":           ("Your Trigger", "🔔", "A custom alert you set has fired."),
    "TECH_SIGNAL":      ("Technical", "📐", "A technical indicator just fired (RSI/MACD/cross/breakout)."),
}

# Base priority per kind (0-100). Boosted by ownership/watchlist/recency.
KIND_PRIORITY = {
    "CONVICTION_LONG": 90,
    "CONVICTION_SHORT": 90,
    "CRYPTO_SPIKE": 89,
    "SETUP_SCAN": 83,
    "THESIS": 76,
    "HIGH_IMPACT_NEWS": 88,
    "PERSON_ACTIVITY": 86,
    "NEWS_VELOCITY": 84,
    "RANK_JUMP": 80,
    "NEW_TOP": 78,
    "VOLUME_SPIKE": 74,
    "SCORE_SURGE": 72,
    "CRYPTO_MOVE": 66,
    "PRICE_MOVE": 64,
    "SENTIMENT_SURGE": 60,
    "EARNINGS_NEAR": 58,
    "EVENT_NEAR": 54,
    "MACRO_NEAR": 52,
    "CUSTOM": 70,
    "TECH_SIGNAL": 68,
}


def _owned() -> set[str]:
    try:
        with sqlite3.connect(DB_PATH) as c:
            return {r[0].upper() for r in c.execute(
                "SELECT DISTINCT symbol FROM positions WHERE quantity > 0").fetchall() if r[0]}
    except Exception:
        return set()


def build_radar(hours: int = 48, limit: int = 40) -> list[dict]:
    """Return prioritized briefing cards from recent alerts, enriched + framed."""
    owned = _owned()
    watch = set(equity_symbols())
    cards: list[dict] = []

    with sqlite3.connect(DB_PATH) as c:
        c.row_factory = sqlite3.Row
        alerts = c.execute(
            f"""SELECT id, symbol, kind, message, payload, created_at
                FROM alerts
                WHERE created_at >= datetime('now', '-{int(hours)} hours')
                ORDER BY created_at DESC""",
        ).fetchall()

        # Latest opportunity snapshot for score enrichment
        score_map = {}
        latest_ts = c.execute("SELECT MAX(snapshot_ts) FROM score_history").fetchone()[0]
        if latest_ts:
            for r in c.execute(
                "SELECT symbol, score, direction, rank FROM score_history WHERE snapshot_ts=?",
                (latest_ts,),
            ):
                score_map[r[0]] = {"score": r[1], "direction": r[2], "rank": r[3]}

        for a in alerts:
            kind = a["kind"]
            meta = KIND_META.get(kind, ("Signal", "•", "Worth a look."))
            cat, icon, why = meta
            base = KIND_PRIORITY.get(kind, 50)

            sym = (a["symbol"] or "").upper()
            is_owned = sym in owned
            is_watch = sym in watch

            priority = base
            if is_owned:
                priority += 18
            elif is_watch:
                priority += 8

            # Recency boost: newer alerts rank higher
            try:
                created = datetime.fromisoformat(a["created_at"].replace("Z", "+00:00"))
                if created.tzinfo is None:
                    created = created.replace(tzinfo=timezone.utc)
                age_h = (datetime.now(timezone.utc) - created).total_seconds() / 3600
                priority += max(0, 10 - age_h)  # up to +10 for very fresh
            except Exception:
                age_h = 0

            # Parse payload for links / extra detail
            url = None
            extra = {}
            try:
                extra = json.loads(a["payload"]) if a["payload"] else {}
                url = extra.get("url")
            except Exception:
                pass

            sc = score_map.get(sym, {})
            score_str = ""
            if sc:
                score_str = f"DK score {sc['score']:.0f} ({sc['direction']}), rank #{sc['rank']}"

            cards.append({
                "priority": round(priority, 1),
                "category": cat,
                "icon": icon,
                "symbol": sym or "—",
                "headline": a["message"],
                "why": why,
                "score_context": score_str,
                "url": url,
                "owned": is_owned,
                "watchlist": is_watch,
                "kind": kind,
                "ts": a["created_at"],
            })

    cards.sort(key=lambda x: x["priority"], reverse=True)
    return cards[:limit]


def opportunity_spotlight(limit: int = 5) -> list[dict]:
    """The names with the most positive signals CONVERGING right now.

    Convergence = high opportunity score + bullish lean + positive recent news
    + (bonus) an upcoming catalyst. This is the 'here's what's lining up' view —
    pointing things out, not telling you to trade them.
    """
    owned = _owned()
    out: list[dict] = []
    with sqlite3.connect(DB_PATH) as c:
        c.row_factory = sqlite3.Row
        latest_ts = c.execute("SELECT MAX(snapshot_ts) FROM score_history").fetchone()[0]
        if not latest_ts:
            return []
        rows = c.execute(
            """SELECT symbol, score, direction, rank, sentiment, price_mom,
                      earn_prox, headline_count_24h
               FROM score_history WHERE snapshot_ts=?
               ORDER BY score DESC""",
            (latest_ts,),
        ).fetchall()

        for r in rows:
            sym = r["symbol"]
            reasons = []
            conviction = 0.0

            if r["score"] is not None and r["score"] >= 45:
                conviction += (r["score"] - 45) * 0.6
                reasons.append(f"opportunity score {r['score']:.0f}")
            if r["direction"] == "bull":
                conviction += 12
                reasons.append("bullish lean")
            if r["sentiment"] is not None and r["sentiment"] > 0.15:
                conviction += r["sentiment"] * 25
                reasons.append(f"positive news tone (+{r['sentiment']:.2f})")
            if r["price_mom"] is not None and r["price_mom"] > 0.1:
                conviction += r["price_mom"] * 15
                reasons.append("upward price momentum")
            if r["earn_prox"] is not None and r["earn_prox"] > 0.3:
                conviction += 10
                reasons.append("earnings catalyst soon")
            if r["headline_count_24h"] and r["headline_count_24h"] >= 5:
                conviction += 6
                reasons.append(f"{r['headline_count_24h']} headlines in 24h")

            # Need at least 2 converging positives to be a "spotlight"
            if len(reasons) < 2 or conviction < 15:
                continue

            # Pull the single best recent headline as the "why now"
            top_news = c.execute(
                """SELECT title, url, sentiment FROM news
                   WHERE symbol=? AND sentiment IS NOT NULL
                     AND fetched_at >= datetime('now', '-3 days')
                   ORDER BY sentiment DESC LIMIT 1""",
                (sym,),
            ).fetchone()

            out.append({
                "symbol": sym,
                "conviction": round(conviction, 1),
                "score": r["score"],
                "direction": r["direction"],
                "rank": r["rank"],
                "reasons": reasons,
                "owned": sym.upper() in owned,
                "catalyst_headline": top_news["title"] if top_news else None,
                "catalyst_url": top_news["url"] if top_news else None,
            })

    out.sort(key=lambda x: x["conviction"], reverse=True)
    return out[:limit]


def watchlist_risks(limit: int = 5) -> list[dict]:
    """Names with NEGATIVE signals converging — so you're not blindsided.

    Same convergence idea but for downside: bearish lean + negative news +
    downward momentum + (bonus) earnings binary risk.
    """
    owned = _owned()
    out: list[dict] = []
    with sqlite3.connect(DB_PATH) as c:
        c.row_factory = sqlite3.Row
        latest_ts = c.execute("SELECT MAX(snapshot_ts) FROM score_history").fetchone()[0]
        if not latest_ts:
            return []
        rows = c.execute(
            """SELECT symbol, score, direction, sentiment, price_mom, earn_prox
               FROM score_history WHERE snapshot_ts=?""",
            (latest_ts,),
        ).fetchall()
        for r in rows:
            sym = r["symbol"]
            reasons = []
            risk = 0.0
            if r["direction"] == "bear":
                risk += 12
                reasons.append("bearish lean")
            if r["sentiment"] is not None and r["sentiment"] < -0.12:
                risk += abs(r["sentiment"]) * 25
                reasons.append(f"negative news tone ({r['sentiment']:.2f})")
            if r["price_mom"] is not None and r["price_mom"] < -0.1:
                risk += abs(r["price_mom"]) * 15
                reasons.append("downward price momentum")
            if r["earn_prox"] is not None and r["earn_prox"] > 0.5:
                risk += 8
                reasons.append("earnings binary risk imminent")
            if len(reasons) < 2 or risk < 14:
                continue
            out.append({
                "symbol": sym,
                "risk": round(risk, 1),
                "reasons": reasons,
                "owned": sym.upper() in owned,
            })
    out.sort(key=lambda x: x["risk"], reverse=True)
    return out[:limit]
