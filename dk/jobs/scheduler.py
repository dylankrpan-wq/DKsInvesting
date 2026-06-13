"""Long-running scheduler. Launch:
    uv run python -m dk.jobs.scheduler

Runs the full poller every POLL_MINUTES (default 15). Keep this terminal
window open; Ctrl+C to stop.
"""
from __future__ import annotations
import os
import signal
import sys
import time
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
from dk.jobs import poller

POLL_MINUTES = int(os.getenv("POLL_MINUTES", "15"))


def _job():
    print(f"\n[{datetime.now():%Y-%m-%d %H:%M:%S}] scheduled poll firing")
    try:
        summary = poller.run_once()
        print(f"  -> {summary}")
    except Exception as e:
        print(f"  !! poll failed: {e}")


def _hourly_job():
    """Top-of-hour consolidated pulse + open perp-setup recap to the phone."""
    try:
        from dk.briefing import hourly
        res = hourly.maybe_send()
        print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] hourly pulse -> {res}")
    except Exception as e:
        print(f"  !! hourly pulse failed: {e}")
    try:
        from dk.analysis import perp_tracker
        rc = perp_tracker.hourly_recap()
        print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] perp recap -> {rc}")
    except Exception as e:
        print(f"  !! perp recap failed: {e}")


def _crypto_spike_job():
    """Fast crypto-derivatives spike check (sub-minute); alerts on short pumps.
    Also runs the perp-setup tracker so TP/stop touches ping promptly."""
    prices = None
    try:
        from dk.jobs import crypto_spike
        res = crypto_spike.run_once()
        if isinstance(res, dict):
            prices = res.pop("_prices", None)  # reuse the snapshot for the tracker
            if res.get("alerts"):
                print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] crypto spike -> {res}")
    except Exception as e:
        print(f"  !! crypto spike failed: {e}")
    try:
        from dk.analysis import perp_tracker
        tr = perp_tracker.check(price_map=prices)
        if tr.get("events"):
            print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] perp tracker -> {tr}")
    except Exception as e:
        print(f"  !! perp tracker failed: {e}")


def _setup_scan_job():
    """Hourly perp setup scan; pushes the top high-R:R setups to the phone."""
    try:
        from dk.analysis import perp_scanner
        res = perp_scanner.scan_and_alert()
        print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] setup scan -> {res}")
    except Exception as e:
        print(f"  !! setup scan failed: {e}")


def _setup_scan_minute() -> int:
    try:
        from dk.analysis import perp_scanner
        return perp_scanner.cron_minute()
    except Exception:
        return 30


def _spike_interval() -> int:
    try:
        from dk.jobs import crypto_spike
        return max(30, crypto_spike.interval_seconds())  # floor 30s to be polite
    except Exception:
        return 90


_BG_SCHED = None


def start_background_scheduler(run_now: bool = True):
    """Start an in-process BackgroundScheduler exactly once per process.

    Used when the dashboard and poller share a single host process (e.g. on
    Railway). Safe to call repeatedly — subsequent calls are no-ops. Returns
    the scheduler instance.
    """
    global _BG_SCHED
    if _BG_SCHED is not None:
        return _BG_SCHED
    sched = BackgroundScheduler(timezone="UTC")
    first_run = datetime.now() if run_now else None
    sched.add_job(_job, IntervalTrigger(minutes=POLL_MINUTES),
                  id="poll", next_run_time=first_run,
                  max_instances=1, coalesce=True)
    # Hourly pulse: top of every hour, 24/7 (sends only when notable).
    # misfire_grace_time=300 so a brief stall at :00 still delivers (the default
    # 1s would silently skip the whole hour since it only fires once).
    sched.add_job(_hourly_job, CronTrigger(minute=0),
                  id="hourly_pulse", max_instances=1, coalesce=True,
                  misfire_grace_time=300)
    # Fast crypto-derivatives spike check (sub-minute).
    spike_s = _spike_interval()
    sched.add_job(_crypto_spike_job, IntervalTrigger(seconds=spike_s),
                  id="crypto_spike", max_instances=1, coalesce=True)
    # Hourly perp setup scan -> phone (offset from the pulse).
    sched.add_job(_setup_scan_job, CronTrigger(minute=_setup_scan_minute()),
                  id="setup_scan", max_instances=1, coalesce=True,
                  misfire_grace_time=300)
    sched.start()
    _BG_SCHED = sched
    print(f"[scheduler] in-process scheduler started "
          f"({POLL_MINUTES} min poll + hourly pulse + {spike_s}s crypto spike "
          f"+ hourly setup scan)")
    return sched


def trigger_now() -> bool:
    """Ask the running in-process scheduler to run the poll job immediately,
    in its background thread (non-blocking). Returns True if triggered."""
    global _BG_SCHED
    if _BG_SCHED is None:
        return False
    job = _BG_SCHED.get_job("poll")
    if not job:
        return False
    try:
        job.modify(next_run_time=datetime.now())
        return True
    except Exception as e:
        print(f"[scheduler] trigger_now failed: {e}")
        return False


def is_running() -> bool:
    return _BG_SCHED is not None


def last_poll_info() -> dict:
    """Best-effort: when is the next scheduled poll?"""
    global _BG_SCHED
    if _BG_SCHED is None:
        return {}
    job = _BG_SCHED.get_job("poll")
    if not job or not job.next_run_time:
        return {}
    return {"next_run": job.next_run_time.isoformat()}


def main():
    sched = BackgroundScheduler(timezone="UTC")
    sched.add_job(_job, IntervalTrigger(minutes=POLL_MINUTES), id="poll", next_run_time=datetime.now())
    sched.add_job(_hourly_job, CronTrigger(minute=0), id="hourly_pulse",
                  max_instances=1, coalesce=True, misfire_grace_time=300)
    spike_s = _spike_interval()
    sched.add_job(_crypto_spike_job, IntervalTrigger(seconds=spike_s),
                  id="crypto_spike", max_instances=1, coalesce=True)
    sched.add_job(_setup_scan_job, CronTrigger(minute=_setup_scan_minute()),
                  id="setup_scan", max_instances=1, coalesce=True, misfire_grace_time=300)
    sched.start()
    print(f"DK scheduler running every {POLL_MINUTES} min + hourly pulse "
          f"+ {spike_s}s crypto spike + hourly setup scan. Ctrl+C to stop.")

    stop = False
    def handle(sig, frame):
        nonlocal stop
        stop = True
    signal.signal(signal.SIGINT, handle)
    signal.signal(signal.SIGTERM, handle)
    try:
        while not stop:
            time.sleep(1)
    finally:
        sched.shutdown(wait=False)
        print("scheduler stopped.")


if __name__ == "__main__":
    main()
