"""Central push gate — one place to control ALL phone/group pushes.

Every scheduled push job checks should_push(channel) before sending, so you get:
  • a master on/off kill-switch
  • quiet hours (ET) to silence overnight noise
  • per-channel toggles (turn a specific push off without touching code)

Config lives in config/watchlist.yaml under `pushes:`. Missing config = all on
(fully backward compatible).
"""
from __future__ import annotations
from dk.config import load_watchlist


def _cfg() -> dict:
    try:
        return load_watchlist().get("pushes") or {}
    except Exception:
        return {}


def pushes_enabled() -> bool:
    return _cfg().get("enabled", True) is not False


def channel_enabled(channel: str | None) -> bool:
    if not channel:
        return True
    return (_cfg().get("channels") or {}).get(channel, True) is not False


def in_quiet_hours() -> bool:
    qc = _cfg().get("quiet_hours_et") or {}
    start, end = qc.get("start"), qc.get("end")
    if start is None or end is None:
        return False
    try:
        from dk.util import session
        h = session.now_et().hour
    except Exception:
        return False
    start, end = int(start), int(end)
    if start == end:
        return False
    if start < end:                 # same-day window (e.g. 1–5)
        return start <= h < end
    return h >= start or h < end     # overnight window (e.g. 21–7)


def should_push(channel: str | None = None) -> bool:
    """True if a push on `channel` is allowed right now."""
    if not pushes_enabled():
        return False
    if in_quiet_hours():
        return False
    return channel_enabled(channel)


def status() -> dict:
    c = _cfg()
    return {
        "enabled": pushes_enabled(),
        "quiet_hours_et": c.get("quiet_hours_et"),
        "in_quiet_hours": in_quiet_hours(),
        "channels": c.get("channels") or {},
    }
