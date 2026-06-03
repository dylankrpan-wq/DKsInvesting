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
from dk.jobs import poller

POLL_MINUTES = int(os.getenv("POLL_MINUTES", "15"))


def _job():
    print(f"\n[{datetime.now():%Y-%m-%d %H:%M:%S}] scheduled poll firing")
    try:
        summary = poller.run_once()
        print(f"  -> {summary}")
    except Exception as e:
        print(f"  !! poll failed: {e}")


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
    sched.start()
    _BG_SCHED = sched
    print(f"[scheduler] in-process scheduler started ({POLL_MINUTES} min interval)")
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
    sched.start()
    print(f"DK scheduler running every {POLL_MINUTES} min. Ctrl+C to stop.")

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
