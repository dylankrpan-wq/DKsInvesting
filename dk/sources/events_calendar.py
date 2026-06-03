"""Load curated events calendar and surface them as alerts ahead-of and day-of."""
from __future__ import annotations
import json
import sqlite3
from datetime import date, datetime, timedelta
import yaml
from dk.config import CONFIG_DIR, DB_PATH


def load_events() -> list[dict]:
    path = CONFIG_DIR / "events.yaml"
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data.get("events") or []


def check_and_alert() -> int:
    """Fire alerts for upcoming high-importance events (day-of and day-before)."""
    today = date.today()
    horizon = today + timedelta(days=1)
    events = load_events()
    n = 0
    with sqlite3.connect(DB_PATH) as c:
        for ev in events:
            try:
                ed = ev.get("date")
                if isinstance(ed, str):
                    ed = date.fromisoformat(ed)
                if not isinstance(ed, date):
                    continue
            except Exception:
                continue
            if ed < today or ed > horizon:
                continue
            if int(ev.get("importance", 1)) < 2:
                continue

            # Dedup per (event title, date)
            event_key = f"event::{ev.get('title', '')}::{ed.isoformat()}"
            existing = c.execute(
                "SELECT 1 FROM alerts WHERE message LIKE ? AND substr(created_at,1,10)=?",
                (f"%{ev.get('title', '')}%", today.isoformat()),
            ).fetchone()
            if existing:
                continue

            sym = ev.get("symbol") or "?"
            days_out = (ed - today).days
            when = "TODAY" if days_out == 0 else f"in {days_out} day"
            msg = f"📣 {ev.get('category', '?')}: {ev.get('title')} — {when} ({ed.isoformat()})"
            c.execute(
                "INSERT INTO alerts (symbol, kind, message, payload) VALUES (?, ?, ?, ?)",
                (sym, "EVENT_NEAR", msg,
                 json.dumps({"event_date": ed.isoformat(),
                              "category": ev.get("category"),
                              "title": ev.get("title"),
                              "importance": ev.get("importance"),
                              "days_out": days_out})),
            )
            n += 1
        c.commit()
    return n
