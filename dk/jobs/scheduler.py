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
    try:
        # Refresh the persistent call-out track record (freezes resolved outcomes).
        from dk.analysis import perp_scorecard
        rows = perp_scorecard.build_ledger()
        s = perp_scorecard.summary(rows)
        print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] perp scorecard -> "
              f"{s['total']} call-outs, {s['wins']}W/{s['losses']}L/{s['open']}open, "
              f"win {s['win_rate_pct']}% exp {s['expectancy_r']}R")
    except Exception as e:
        print(f"  !! perp scorecard failed: {e}")


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


def _premarket_scan_job():
    """Pre-market US-equity gap scan; self-gates to the pre-market window so it's
    a cheap no-op overnight, during RTH, and on weekends/holidays."""
    try:
        from dk.jobs import premarket_scan
        res = premarket_scan.run_once()
        if res.get("alerts"):
            print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] premarket scan -> {res}")
    except Exception as e:
        print(f"  !! premarket scan failed: {e}")


def _equity_ideas_job():
    """Scan the broad equity universe for multi-horizon ideas; push the best few
    with a Claude thesis, silently track the rest. Trading-day gated inside."""
    try:
        from dk.analysis import equity_ideas
        res = equity_ideas.scan_and_alert()
        print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] equity ideas -> {res}")
    except Exception as e:
        print(f"  !! equity ideas failed: {e}")


def _equity_scan_hours() -> str:
    try:
        from dk.config import load_watchlist
        return str((load_watchlist().get("equity_ideas") or {}).get("scan_hours_utc", "14,18"))
    except Exception:
        return "14,18"


def _setup_scan_minute() -> int:
    try:
        from dk.analysis import perp_scanner
        return perp_scanner.cron_minute()
    except Exception:
        return 30


def _premarket_interval_min() -> int:
    try:
        from dk.config import load_watchlist
        return max(5, int((load_watchlist().get("premarket") or {}).get("scan_minutes", 15)))
    except Exception:
        return 15


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
                  max_instances=1, coalesce=True, misfire_grace_time=300)
    # Hourly pulse: top of every hour, 24/7 (sends only when notable).
    # misfire_grace_time=300 so a brief stall at :00 still delivers (the default
    # 1s would silently skip the whole hour since it only fires once).
    sched.add_job(_hourly_job, CronTrigger(minute=0),
                  id="hourly_pulse", max_instances=1, coalesce=True,
                  misfire_grace_time=300)
    # Fast crypto-derivatives spike check (sub-minute).
    spike_s = _spike_interval()
    sched.add_job(_crypto_spike_job, IntervalTrigger(seconds=spike_s),
                  id="crypto_spike", max_instances=1, coalesce=True,
                  misfire_grace_time=60)
    # Hourly perp setup scan -> phone (offset from the pulse).
    sched.add_job(_setup_scan_job, CronTrigger(minute=_setup_scan_minute()),
                  id="setup_scan", max_instances=1, coalesce=True,
                  misfire_grace_time=300)
    # Pre-market US-equity gap scan (self-gates to the pre-market window).
    # (The overnight digest + morning brief are poller-driven + ET-gated, so they
    # live in the poll cycle, not here — DST-correct without APScheduler tz.)
    pm_min = _premarket_interval_min()
    sched.add_job(_premarket_scan_job, IntervalTrigger(minutes=pm_min),
                  id="premarket_scan", max_instances=1, coalesce=True,
                  misfire_grace_time=300)
    # Equity multi-horizon idea scan -> phone (with theses), trading days only.
    eq_hours = _equity_scan_hours()
    sched.add_job(_equity_ideas_job, CronTrigger(hour=eq_hours, minute=15),
                  id="equity_ideas", max_instances=1, coalesce=True,
                  misfire_grace_time=600)
    sched.start()
    _BG_SCHED = sched
    # Catch-up: if we booted (deploy/restart) during RTH on a trading day and no
    # equity ideas have gone out today, run one now — otherwise a restart landing
    # between the two cron times means no ideas until the next slot. The 24h
    # cooldown + _fresh guard make a catch-up safe (no duplicate pushes).
    try:
        import sqlite3
        from dk.util import session
        from dk.config import DB_PATH
        if session.is_trading_day() and session.is_rth():
            with sqlite3.connect(DB_PATH) as _c:
                done = _c.execute("SELECT 1 FROM alerts WHERE kind='EQUITY_IDEA' "
                                  "AND created_at >= date('now') LIMIT 1").fetchone()
            if not done:
                sched.modify_job("equity_ideas", next_run_time=datetime.now())
                print("[scheduler] equity-ideas catch-up scheduled (RTH, none yet today)")
    except Exception as e:
        print(f"[scheduler] equity-ideas catch-up skipped: {e}")
    print(f"[scheduler] in-process scheduler started "
          f"({POLL_MINUTES} min poll + hourly pulse + {spike_s}s crypto spike "
          f"+ hourly setup scan + {pm_min}m pre-market scan + equity ideas @{eq_hours}h UTC)")
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
    # Mutually exclusive with the dashboard's in-process scheduler. Running both
    # against the same DB = two schedulers firing every job = duplicate phone
    # pushes (and a register race). Refuse so the operator can't do it by accident.
    if os.getenv("DK_INPROCESS_SCHEDULER") == "1":
        print("[scheduler] refusing to start: DK_INPROCESS_SCHEDULER=1 means the "
              "dashboard already runs the in-process scheduler. Unset it to run "
              "this standalone scheduler, or just run the dashboard.")
        return
    sched = BackgroundScheduler(timezone="UTC")
    sched.add_job(_job, IntervalTrigger(minutes=POLL_MINUTES), id="poll",
                  next_run_time=datetime.now(), max_instances=1, coalesce=True,
                  misfire_grace_time=300)
    sched.add_job(_hourly_job, CronTrigger(minute=0), id="hourly_pulse",
                  max_instances=1, coalesce=True, misfire_grace_time=300)
    spike_s = _spike_interval()
    sched.add_job(_crypto_spike_job, IntervalTrigger(seconds=spike_s),
                  id="crypto_spike", max_instances=1, coalesce=True,
                  misfire_grace_time=60)
    sched.add_job(_setup_scan_job, CronTrigger(minute=_setup_scan_minute()),
                  id="setup_scan", max_instances=1, coalesce=True, misfire_grace_time=300)
    pm_min = _premarket_interval_min()
    sched.add_job(_premarket_scan_job, IntervalTrigger(minutes=pm_min),
                  id="premarket_scan", max_instances=1, coalesce=True,
                  misfire_grace_time=300)
    eq_hours = _equity_scan_hours()
    sched.add_job(_equity_ideas_job, CronTrigger(hour=eq_hours, minute=15),
                  id="equity_ideas", max_instances=1, coalesce=True,
                  misfire_grace_time=600)
    sched.start()
    print(f"DK scheduler running every {POLL_MINUTES} min + hourly pulse "
          f"+ {spike_s}s crypto spike + hourly setup scan + {pm_min}m pre-market "
          f"scan + equity ideas @{eq_hours}h UTC. Ctrl+C to stop.")

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
