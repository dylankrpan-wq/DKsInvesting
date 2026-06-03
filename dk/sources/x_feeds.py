"""Pull X (Twitter) posts via Nitter / RSSHub RSS, with multi-instance fallback.

X killed free API access in 2023. We rely on community-run RSS proxies:
  - Nitter — open-source X frontend; instances live and die regularly
  - RSSHub — open-source aggregator with /twitter/user/<handle>
Both can fail / rate-limit / get blocked. We try each in turn and stop at
the first that returns parseable items.

When all instances are down, we still get value from:
  - News coverage of newsworthy posts (Bloomberg/Reuters/Benzinga write them up)
  - The direct X profile link shown in the UI
"""
from __future__ import annotations
import hashlib
import feedparser
from datetime import datetime, timezone
from dk.config import CONFIG_DIR
from dk.store import db
import yaml

# Rotating list of RSS proxy templates. {handle} gets substituted.
# Ordered roughly by reliability as of late 2025. Edit freely.
INSTANCE_TEMPLATES = [
    "https://rsshub.app/twitter/user/{handle}",
    "https://nitter.poast.org/{handle}/rss",
    "https://nitter.privacydev.net/{handle}/rss",
    "https://nitter.net/{handle}/rss",
    "https://nitter.cz/{handle}/rss",
]


def _hash_id(handle: str, link: str) -> str:
    return hashlib.sha1(f"x|{handle}|{link}".encode()).hexdigest()[:24]


def _load_people_with_x() -> list[dict]:
    path = CONFIG_DIR / "people.yaml"
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    out = []
    for p in data.get("people") or []:
        if p.get("x_handle"):
            out.append(p)
    return out


def _try_instance(template: str, handle: str, person: dict) -> list[dict]:
    url = template.format(handle=handle)
    try:
        feed = feedparser.parse(
            url, request_headers={"User-Agent": "DK-Investing/0.1 (personal research)"}
        )
    except Exception as e:
        print(f"[x_feeds] {handle} via {template}: {e}")
        return []

    if not feed.entries:
        return []

    rows: list[dict] = []
    for entry in feed.entries[:20]:
        title = (entry.get("title", "") or "").strip()
        summary = (entry.get("summary", "") or "")[:1500]
        link = entry.get("link", "")
        if not (title or summary) or not link:
            continue
        published = entry.get("published") or entry.get("updated") or ""
        rows.append({
            "id": _hash_id(handle, link),
            "symbol": (person.get("affects") or [None])[0] if person.get("affects") else None,
            "region": "X",
            "source": f"X:@{handle}",
            "title": title[:300] or summary[:300],
            "summary": summary,
            "url": link,
            "published": published,
            "is_breaking": 1,  # power-player posts are inherently noteworthy
        })
    return rows


def fetch_for(handle: str, person: dict | None = None) -> list[dict]:
    """Try each instance in turn for a single handle. Return rows from first success."""
    person = person or {"x_handle": handle, "affects": []}
    for template in INSTANCE_TEMPLATES:
        rows = _try_instance(template, handle, person)
        if rows:
            return rows
    return []


def fetch_all() -> int:
    """Pull X posts for every tracked person with an x_handle."""
    people = _load_people_with_x()
    all_rows: list[dict] = []
    success_handles: list[str] = []
    failed_handles: list[str] = []
    for p in people:
        handle = p["x_handle"]
        rows = fetch_for(handle, p)
        if rows:
            all_rows.extend(rows)
            success_handles.append(handle)
        else:
            failed_handles.append(handle)
    if failed_handles:
        print(f"[x_feeds] No instance worked for: {failed_handles}")
    if not all_rows:
        return 0
    return db.upsert_news(all_rows)
