"""Track market-moving people. Loads config/people.yaml, scans recent news for
mentions, and surfaces 'PERSON_ACTIVITY' alerts when a tracked person is
mentioned with a breaking keyword or extreme sentiment.
"""
from __future__ import annotations
import json
import sqlite3
from datetime import datetime, timedelta, timezone
import yaml
from dk.config import CONFIG_DIR, DB_PATH


def load_people() -> list[dict]:
    path = CONFIG_DIR / "people.yaml"
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data.get("people") or []


def _person_matches_text(person: dict, text: str) -> bool:
    text_lower = (text or "").lower()
    for alias in person.get("aliases") or []:
        if alias.lower() in text_lower:
            return True
    return False


def _person_has_keyword(person: dict, text: str) -> bool:
    text_lower = (text or "").lower()
    for kw in person.get("keywords") or []:
        if kw.lower() in text_lower:
            return True
    return False


def detect_and_alert(window_hours: int = 4) -> int:
    """Scan recent news for tracked people, fire alerts for matches."""
    people = load_people()
    if not people:
        return 0

    cutoff = (datetime.now(timezone.utc) - timedelta(hours=window_hours)).isoformat()
    n = 0
    with sqlite3.connect(DB_PATH) as c:
        articles = c.execute(
            """SELECT id, symbol, source, title, summary, url, sentiment, is_breaking, fetched_at
               FROM news WHERE fetched_at >= ? ORDER BY fetched_at DESC""",
            (cutoff,),
        ).fetchall()

        for (nid, sym, source, title, summary, url, sentiment, is_breaking,
             fetched) in articles:
            combined = f"{title or ''} {summary or ''}"
            for person in people:
                if not _person_matches_text(person, combined):
                    continue

                weight = int(person.get("weight", 1))
                has_kw = _person_has_keyword(person, combined)
                strong_sentiment = (sentiment is not None and abs(sentiment) >= 0.4)

                # Fire if: heavy-pull person (weight>=2) is mentioned WITH either
                # a breaking flag, their own keyword, or strong sentiment.
                if weight < 2 and not (is_breaking or has_kw):
                    continue
                if weight >= 2 and not (is_breaking or has_kw or strong_sentiment):
                    continue

                # Dedup per (person, article)
                marker = f"person::{person['id']}::{nid}"
                existing = c.execute(
                    "SELECT 1 FROM alerts WHERE payload LIKE ? LIMIT 1",
                    (f'%"marker": "{marker}"%',),
                ).fetchone()
                if existing:
                    continue

                affects = ", ".join(person.get("affects") or [])
                msg = (f"📣 {person['name']} ({person.get('role', '')}): "
                       f"\"{title[:120]}\" — affects: {affects}")
                c.execute(
                    "INSERT INTO alerts (symbol, kind, message, payload) VALUES (?, ?, ?, ?)",
                    (sym or affects.split(",")[0].strip() or "?",
                     "PERSON_ACTIVITY", msg,
                     json.dumps({"marker": marker, "person_id": person['id'],
                                  "person_name": person['name'],
                                  "url": url, "source": source,
                                  "sentiment": sentiment, "is_breaking": is_breaking,
                                  "weight": weight})),
                )
                n += 1
        c.commit()
    return n


def person_mention_counts(hours: int = 24) -> list[dict]:
    """Return mention counts for each tracked person over the last N hours."""
    people = load_people()
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    out = []
    with sqlite3.connect(DB_PATH) as c:
        articles = c.execute(
            "SELECT title, summary, sentiment FROM news WHERE fetched_at >= ?",
            (cutoff,),
        ).fetchall()
        for person in people:
            count = 0
            sentiments = []
            for title, summary, senti in articles:
                if _person_matches_text(person, f"{title or ''} {summary or ''}"):
                    count += 1
                    if senti is not None:
                        sentiments.append(senti)
            if count == 0:
                continue
            avg_s = sum(sentiments) / len(sentiments) if sentiments else None
            out.append({
                "id": person["id"],
                "name": person["name"],
                "role": person.get("role", ""),
                "weight": int(person.get("weight", 1)),
                "mentions": count,
                "avg_sentiment": avg_s,
                "affects": ", ".join(person.get("affects") or []),
            })
    out.sort(key=lambda r: (r["weight"], r["mentions"]), reverse=True)
    return out
