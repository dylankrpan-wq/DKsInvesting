"""Hourly pulse — a consolidated activity summary texted on the hour, 24/7.

Distinct from the two existing phone paths:
  - per-cycle digest (dk/notify/sms.push_digest): instant live-event alerts
  - daily desk brief (dk/briefing/desk_brief): once-a-day Claude synthesis

The hourly pulse rolls up the trailing 60 minutes of the alerts table into one
compact message plus a market-pulse line, and sends ONLY when the hour had
notable activity (any alert fired). Quiet hours stay silent — no heartbeat spam.

Read-only over the alerts table; it does not touch the sms_sent flag the
per-cycle digest manages, so the two never fight over the same rows.
"""
from __future__ import annotations
import re
import sqlite3
from datetime import datetime, timezone
from dk.config import DB_PATH, load_watchlist

# Strip a leading emoji/punctuation run so section emoji isn't doubled by one
# already baked into the alert message ("🎯 LONG setup…" -> "LONG setup…").
# Excludes + - . and digits from the strip set so a message that leads with a
# signed move ("-15% NVDA", "📉 -8% AMD") keeps its sign — dropping it would
# flip a down-move into reading like an up-move.
_LEADING_GLYPHS = re.compile(r"^[^\w$+\-.]+")

# TECH_SIGNAL is per-item low-signal (RSI crossed 50, etc.); a lone one should
# NOT make an hour "notable". Everything else (a 5%+ price move, volume spike,
# conviction setup) is meaningful on its own.
_LOW_SIGNAL_KINDS = {"TECH_SIGNAL"}

# Compact per-kind formatting: (emoji, short label, max items shown).
_KIND_FMT = {
    "CONVICTION_LONG":  ("🎯", "Long setups", 5),
    "CONVICTION_SHORT": ("🎯", "Short setups", 5),
    "SETUP_SCAN":       ("🎯", "Scanner setups", 5),
    "HIGH_IMPACT_NEWS": ("⚡", "Breaking", 4),
    "NEWS_VELOCITY":    ("📡", "Live events", 3),
    "PRICE_MOVE":       ("💥", "Movers", 6),
    "VOLUME_SPIKE":     ("🔊", "Volume spikes", 4),
    "CRYPTO_SPIKE":     ("🚨", "Crypto spikes", 5),
    "CRYPTO_MOVE":      ("🪙", "Crypto", 4),
    "RANK_JUMP":        ("🚀", "Rank jumps", 4),
    "NEW_TOP":          ("⭐", "New top-5", 4),
    "SCORE_SURGE":      ("📈", "Score surges", 4),
    "PERSON_ACTIVITY":  ("📣", "Power players", 3),
    "EVENT_NEAR":       ("📅", "Events", 3),
    "TECH_SIGNAL":      ("📐", "Tech signals", 4),
}
# Order pulse sections by importance (conviction first, context last).
_KIND_ORDER = [
    "CONVICTION_LONG", "CONVICTION_SHORT", "CRYPTO_SPIKE", "SETUP_SCAN",
    "HIGH_IMPACT_NEWS", "NEWS_VELOCITY", "PRICE_MOVE", "VOLUME_SPIKE",
    "CRYPTO_MOVE", "RANK_JUMP", "NEW_TOP", "SCORE_SURGE", "PERSON_ACTIVITY",
    "EVENT_NEAR", "TECH_SIGNAL",
]


def _cfg() -> dict:
    return (load_watchlist().get("hourly") or {})


def _clean(msg: str) -> str:
    """Trim and drop a leading emoji/punctuation run (the alert message already
    carries the symbol, so no prefix is added by the caller)."""
    return _LEADING_GLYPHS.sub("", (msg or "").strip())


def _instant_kinds() -> set[str]:
    """Kinds already texted as they fire by the per-cycle digest — the pulse
    skips rows it already pinged so the phone isn't notified twice."""
    from dk.notify import sms
    return set((load_watchlist().get("sms") or {}).get("live_kinds")
               or sms.DEFAULT_LIVE_KINDS)


def build_summary(window_min: int = 60, max_per_kind: int = 5,
                  min_notable: int = 3) -> dict:
    """Roll up the trailing window's alerts (only those NOT already instant-
    texted) plus a market-pulse line. Returns {notable, text, alert_count}.
    notable requires at least one meaningful alert (or a cluster of low-signal
    ones), so a lone tech signal doesn't fire a pulse every hour."""
    lines: list[str] = []
    now = datetime.now(timezone.utc)
    instant_kinds = _instant_kinds()

    with sqlite3.connect(DB_PATH) as c:
        c.row_factory = sqlite3.Row

        # Market pulse (always shown as context, never the trigger by itself)
        macro = c.execute(
            "SELECT label, chg_pct FROM macro_context").fetchall()
        pulse_bits = []
        for m in macro:
            if m["chg_pct"] is None:
                continue
            arrow = "▲" if m["chg_pct"] >= 0 else "▼"
            pulse_bits.append(f"{m['label']} {arrow}{abs(m['chg_pct']):.1f}%")
        fg = c.execute(
            "SELECT composite, label FROM market_sentiment "
            "ORDER BY snapshot_ts DESC LIMIT 1").fetchone()
        if fg and fg["composite"] is not None:
            pulse_bits.append(f"F&G {fg['composite']:.0f} {fg['label']}")

        rows = c.execute(
            f"""SELECT kind, symbol, message, created_at, sms_sent FROM alerts
                WHERE created_at >= datetime('now', '-{int(window_min)} minutes')
                ORDER BY created_at DESC""").fetchall()

    # Skip rows already delivered by the instant digest. A live-kind row that
    # was never texted (digest off/failed → sms_sent=0) still rolls up here.
    by_kind: dict[str, list[sqlite3.Row]] = {}
    seen: set[tuple] = set()
    for r in rows:
        if r["kind"] in instant_kinds and r["sms_sent"]:
            continue
        key = (r["symbol"], r["kind"])
        if key in seen:
            continue
        seen.add(key)
        by_kind.setdefault(r["kind"], []).append(r)

    alert_count = len(seen)
    meaningful = sum(1 for (_, kind) in seen if kind not in _LOW_SIGNAL_KINDS)

    header = f"📊 DK hourly pulse — {now:%H:%M} UTC"
    if pulse_bits:
        lines.append("Market: " + " · ".join(pulse_bits))

    for kind in _KIND_ORDER:
        items = by_kind.get(kind)
        if not items:
            continue
        emoji, label, cap = _KIND_FMT.get(kind, ("•", kind, max_per_kind))
        cap = min(cap, max_per_kind)
        shown = items[:cap]
        more = len(items) - len(shown)
        # Detailed kinds keep more of the message; compact kinds (movers etc.)
        # already lead with the symbol + the move, so a short slice is enough.
        item_cap = 120 if kind in (
            "CONVICTION_LONG", "CONVICTION_SHORT", "HIGH_IMPACT_NEWS",
            "NEWS_VELOCITY", "PERSON_ACTIVITY", "EVENT_NEAR", "TECH_SIGNAL") else 70
        cleaned = [_clean(i["message"])[:item_cap] for i in shown]
        body = "; ".join(t for t in cleaned if t)
        if not body:
            continue
        suffix = f" (+{more} more)" if more > 0 else ""
        lines.append(f"{emoji} {label} ({len(items)}): {body}{suffix}")

    # Notable = at least one meaningful alert, or a cluster of low-signal ones.
    notable = meaningful >= 1 or alert_count >= min_notable
    text = header + "\n" + "\n".join(lines) if lines else header
    return {"notable": notable, "text": text, "alert_count": alert_count}


def maybe_send() -> dict:
    """Scheduler entry: build the pulse and send it only when notable.
    No-op when disabled or when no phone channel is configured."""
    cfg = _cfg()
    if not cfg.get("enabled", True):
        return {"skipped": "disabled"}

    from dk.notify import sms
    if not sms.is_configured():
        return {"skipped": "no phone channel configured"}

    summary = build_summary(
        window_min=int(cfg.get("window_minutes", 60)),
        max_per_kind=int(cfg.get("max_per_kind", 5)),
        min_notable=int(cfg.get("min_notable", 3)),
    )
    if not summary["notable"]:
        return {"skipped": "quiet hour — nothing notable", "alert_count": 0}

    sent = sms.send_summary(summary["text"])
    return {"sent": sent, "alert_count": summary["alert_count"],
            "channel": sms.active_channel()}


if __name__ == "__main__":
    print(maybe_send())
