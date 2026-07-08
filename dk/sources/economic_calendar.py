"""US economic data prints — actual vs estimate vs previous.

Uses Financial Modeling Prep's economic calendar (free tier). When a high-impact
US release posts its ACTUAL, emits an ECON_PRINT alert with the surprise vs
consensus (e.g. "CPI 3.1% vs 3.2% est — cooler than expected"). No-op w/o key.
"""
from __future__ import annotations
import json
import sqlite3
from dk.config import DB_PATH, get_key

_US = {"US", "USA", "United States"}


def _fmt(v):
    if v is None:
        return "—"
    try:
        f = float(v)
        return f"{f:g}"
    except (TypeError, ValueError):
        return str(v)


def fetch_and_alert() -> dict:
    key = get_key("FMP_API_KEY")
    if not key:
        return {"configured": False, "alerts": 0}
    import requests
    try:
        r = requests.get(
            "https://financialmodelingprep.com/api/v3/economic_calendar",
            params={"apikey": key}, timeout=15,
        )
        if r.status_code != 200:
            return {"configured": True, "alerts": 0, "http": r.status_code}
        data = r.json()
    except Exception as e:
        print(f"[econ] {e}")
        return {"configured": True, "alerts": 0, "error": str(e)}

    n = 0
    with sqlite3.connect(DB_PATH) as c:
        for ev in (data or []):
            if (ev.get("country") or "") not in _US:
                continue
            impact = (ev.get("impact") or "").lower()
            if impact not in ("high", "medium"):
                continue
            actual = ev.get("actual")
            if actual is None:
                continue  # not released yet
            name = ev.get("event") or "?"
            date = ev.get("date") or ""
            marker = f"econ::{name}::{date}"
            if c.execute("SELECT 1 FROM alerts WHERE kind='ECON_PRINT' AND payload LIKE ? LIMIT 1",
                         (f'%"m": "{marker}"%',)).fetchone():
                continue
            est, prev = ev.get("estimate"), ev.get("previous")
            surprise = ""
            try:
                if est is not None:
                    a, e = float(actual), float(est)
                    if a > e:
                        surprise = " — hotter than expected"
                    elif a < e:
                        surprise = " — cooler than expected"
                    else:
                        surprise = " — in line"
            except (TypeError, ValueError):
                pass
            impact_icon = "🔴" if impact == "high" else "🟠"
            msg = (f"{impact_icon} 📊 {name}: actual {_fmt(actual)} "
                   f"vs est {_fmt(est)} (prev {_fmt(prev)}){surprise}")
            c.execute("INSERT INTO alerts (symbol, kind, message, payload) VALUES (?,?,?,?)",
                      (None, "ECON_PRINT", msg,
                       json.dumps({"m": marker, "actual": actual, "estimate": est,
                                   "previous": prev, "impact": impact})))
            n += 1
        c.commit()
    return {"configured": True, "alerts": n}
