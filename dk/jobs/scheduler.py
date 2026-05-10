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
