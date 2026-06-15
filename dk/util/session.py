"""US market-session clock (America/New_York, DST-correct via zoneinfo).

The system runs in UTC; this is the single place that knows what phase the US
equity session is in, so jobs can gate themselves (run the pre-market scan only
pre-market, skip wasteful equity work overnight, etc.) without each one
re-deriving the ET offset. Crypto loops ignore this — crypto trades 24/7.

Phases (ET, regular trading days):
  premarket   04:00 - 09:30
  rth         09:30 - 16:00   (regular trading hours)
  afterhours  16:00 - 20:00
  overnight   20:00 - 04:00   (+ weekends + US market holidays)
"""
from __future__ import annotations
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

PREMARKET_OPEN = time(4, 0)
RTH_OPEN = time(9, 30)
RTH_CLOSE = time(16, 0)
AFTERHOURS_CLOSE = time(20, 0)

# US equity-market full-day closures (NYSE/Nasdaq). Half-days (early closes) are
# not special-cased — they still count as RTH, which is fine for our gating.
MARKET_HOLIDAYS = {
    # 2026
    "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25",
    "2026-06-19", "2026-07-03", "2026-09-07", "2026-11-26", "2026-12-25",
    # 2027 (so the gate keeps working past New Year without a redeploy)
    "2027-01-01", "2027-01-18", "2027-02-15", "2027-03-26", "2027-05-31",
    "2027-06-18", "2027-07-05", "2027-09-06", "2027-11-25", "2027-12-24",
}


def now_et() -> datetime:
    """Current time in US/Eastern (DST-aware)."""
    return datetime.now(timezone.utc).astimezone(ET)


def is_trading_day(dt: datetime | None = None) -> bool:
    """Mon-Fri and not a full-day market holiday."""
    dt = dt or now_et()
    if dt.weekday() >= 5:  # Sat/Sun
        return False
    return dt.strftime("%Y-%m-%d") not in MARKET_HOLIDAYS


def session_phase(dt: datetime | None = None) -> str:
    """One of: 'premarket' | 'rth' | 'afterhours' | 'overnight'.

    Weekends and holidays are 'overnight' (markets shut, only crypto/futures move).
    """
    dt = dt or now_et()
    if not is_trading_day(dt):
        return "overnight"
    t = dt.time()
    if PREMARKET_OPEN <= t < RTH_OPEN:
        return "premarket"
    if RTH_OPEN <= t < RTH_CLOSE:
        return "rth"
    if RTH_CLOSE <= t < AFTERHOURS_CLOSE:
        return "afterhours"
    return "overnight"


def is_premarket(dt: datetime | None = None) -> bool:
    return session_phase(dt) == "premarket"


def is_rth(dt: datetime | None = None) -> bool:
    return session_phase(dt) == "rth"


def is_afterhours(dt: datetime | None = None) -> bool:
    return session_phase(dt) == "afterhours"


def is_overnight(dt: datetime | None = None) -> bool:
    return session_phase(dt) == "overnight"


def is_premarket_window(dt: datetime | None = None) -> bool:
    """Looser gate for the pre-market scan: premarket OR the first ~15 min of RTH,
    so a gap that's still developing at the open isn't dropped mid-scan."""
    dt = dt or now_et()
    if not is_trading_day(dt):
        return False
    return PREMARKET_OPEN <= dt.time() < time(9, 45)


if __name__ == "__main__":
    n = now_et()
    print(f"ET now: {n:%Y-%m-%d %H:%M:%S %Z} (weekday {n.weekday()})")
    print(f"trading day: {is_trading_day()}  phase: {session_phase()}  "
          f"premarket_window: {is_premarket_window()}")
