"""Optional Discord webhook notifier. No-op if DISCORD_WEBHOOK_URL is unset."""
from __future__ import annotations
import requests
from dk.config import get_key
from dk.jobs import alerts as alert_engine

KIND_EMOJI = {
    "PRICE_MOVE": ":chart_with_upwards_trend:",
    "VOLUME_SPIKE": ":fire:",
    "EARNINGS_NEAR": ":calendar_spiral:",
    "SENTIMENT_SURGE": ":newspaper:",
    "CRYPTO_MOVE": ":coin:",
}


def push_unsent() -> int:
    url = get_key("DISCORD_WEBHOOK_URL")
    if not url:
        return 0
    pending = alert_engine.fetch_unsent()
    if not pending:
        return 0
    sent_ids: list[int] = []
    for a in pending:
        emoji = KIND_EMOJI.get(a["kind"], ":bell:")
        content = f"{emoji} **{a['kind']}** — {a['message']}"
        try:
            r = requests.post(url, json={"content": content}, timeout=10)
            if r.status_code in (200, 204):
                sent_ids.append(a["id"])
            else:
                print(f"[discord] HTTP {r.status_code}: {r.text[:200]}")
        except Exception as e:
            print(f"[discord] {e}")
            break
    alert_engine.mark_sent(sent_ids)
    return len(sent_ids)
