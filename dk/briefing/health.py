"""System health / diagnostics — answers 'is data actually being fetched & stored?'

Surfaced in the dashboard so we can SEE what's working instead of guessing:
scheduler state, last poll counts, and row counts per table.
"""
from __future__ import annotations
import json
import os
import sqlite3
from dk.config import DB_PATH, DATA_DIR


_COUNT_TABLES = [
    "prices", "news", "earnings", "alerts", "score_history",
    "market_sentiment", "theme_scores", "trending_mentions",
    "macro_context", "positions",
]


def gather() -> dict:
    out: dict = {}

    # Env / paths
    out["env"] = {
        "DK_INPROCESS_SCHEDULER": os.getenv("DK_INPROCESS_SCHEDULER"),
        "DK_DATA_DIR": os.getenv("DK_DATA_DIR"),
        "POLL_MINUTES": os.getenv("POLL_MINUTES"),
    }
    out["data_dir"] = str(DATA_DIR)
    out["db_path"] = str(DB_PATH)

    # DB writable?
    try:
        with sqlite3.connect(DB_PATH, timeout=5) as c:
            c.execute("CREATE TABLE IF NOT EXISTS _health_probe (x INTEGER)")
            c.execute("DROP TABLE IF EXISTS _health_probe")
        out["db_writable"] = True
    except Exception as e:
        out["db_writable"] = False
        out["db_error"] = str(e)

    # Scheduler state
    try:
        from dk.jobs.scheduler import is_running, last_poll_info
        out["scheduler_running"] = is_running()
        out["scheduler"] = last_poll_info()
    except Exception as e:
        out["scheduler_running"] = False
        out["scheduler_error"] = str(e)

    # Poll status + last summary
    try:
        from dk.store import db as store
        ps = store.get_poll_status()
        out["poll_status"] = ps.get("status")
        out["poll_started_at"] = ps.get("started_at")
        out["poll_finished_at"] = ps.get("finished_at")
        try:
            out["last_summary"] = json.loads(ps.get("summary_json") or "{}")
        except Exception:
            out["last_summary"] = {}
    except Exception as e:
        out["poll_status_error"] = str(e)

    # Row counts
    counts = {}
    try:
        with sqlite3.connect(DB_PATH, timeout=5) as c:
            for t in _COUNT_TABLES:
                try:
                    counts[t] = c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                except Exception:
                    counts[t] = "—"
    except Exception as e:
        out["counts_error"] = str(e)
    out["row_counts"] = counts

    return out


def verdict(h: dict) -> tuple[str, str]:
    """Return (status_emoji_label, plain-English diagnosis)."""
    counts = h.get("row_counts", {})
    prices = counts.get("prices", 0) or 0
    news = counts.get("news", 0) or 0
    sched = h.get("scheduler_running")

    if not isinstance(prices, int):
        prices = 0
    if not isinstance(news, int):
        news = 0

    if prices > 0 and news > 0:
        return ("🟢 Healthy", "Prices and news are both populated — data pipeline is working.")
    if news > 0 and prices == 0:
        return ("🟡 Prices blocked",
                "News works but prices are empty — yfinance is being blocked from this host's IP. "
                "Need a datacenter-friendly price source (Stooq w/ key, or Twelve Data / Finnhub).")
    if prices == 0 and news == 0:
        if not sched:
            return ("🔴 Scheduler not running",
                    "No data and the background scheduler isn't running. The first page load "
                    "should start it — try clicking Refresh data, or check the start command.")
        return ("🔴 Poll not completing",
                "Scheduler is running but no data landed yet. Either the first poll hasn't "
                "finished, or every source is failing. Check Railway logs for exceptions.")
    return ("🟡 Partial", "Some data present — see counts below.")
