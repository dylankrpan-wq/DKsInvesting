from __future__ import annotations
from datetime import date, timedelta
import requests
from dk.config import get_key
from dk.store import db


def fetch_calendar(days_ahead: int = 30) -> int:
    key = get_key("FINNHUB_KEY")
    if not key:
        return 0
    today = date.today()
    end = today + timedelta(days=days_ahead)
    try:
        r = requests.get(
            "https://finnhub.io/api/v1/calendar/earnings",
            params={"from": today.isoformat(), "to": end.isoformat(), "token": key},
            timeout=15,
        )
        if r.status_code != 200:
            print(f"[finnhub] calendar HTTP {r.status_code}")
            return 0
        data = r.json()
    except Exception as e:
        print(f"[finnhub] {e}")
        return 0

    rows = []
    for e in data.get("earningsCalendar", []):
        rows.append({
            "symbol": e.get("symbol"),
            "report_date": e.get("date"),
            "eps_estimate": e.get("epsEstimate"),
            "eps_actual": e.get("epsActual"),
            "revenue_estimate": e.get("revenueEstimate"),
            "revenue_actual": e.get("revenueActual"),
        })
    return db.upsert_earnings(rows)
