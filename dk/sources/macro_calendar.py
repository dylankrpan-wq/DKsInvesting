"""Load curated macro events from config/macro_calendar.yaml into the DB."""
from __future__ import annotations
import hashlib
import yaml
from dk.config import CONFIG_DIR
from dk.store import db


def _hash(date: str, title: str) -> str:
    return hashlib.sha1(f"{date}|{title}".encode()).hexdigest()[:24]


def load() -> int:
    path = CONFIG_DIR / "macro_calendar.yaml"
    if not path.exists():
        return 0
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    rows = []
    for ev in data.get("events", []):
        d = str(ev["date"])
        title = ev.get("title", "")
        rows.append({
            "id": _hash(d, title),
            "event_date": d,
            "region": ev.get("region", "US"),
            "category": ev.get("category", "OTHER"),
            "title": title,
            "importance": int(ev.get("importance", 1)),
            "source": "config/macro_calendar.yaml",
            "notes": ev.get("notes", ""),
        })
    return db.upsert_macro(rows)
