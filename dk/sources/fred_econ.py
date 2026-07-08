"""US economic data prints via FRED (Federal Reserve Economic Data) — FREE.

FMP put its economic calendar behind a paywall, so we read the actual releases
straight from FRED. FRED carries no consensus estimate, so we report the actual
vs the PREVIOUS print (trend / surprise-vs-prior) — still the market-moving read.
Emits ECON_PRINT alerts, deduped per series + release period.

Free API key (instant): https://fred.stlouisfed.org/docs/api/api_key.html
No-op without FRED_API_KEY.

Uses FRED's server-side `units` transform so we get the number the market cares
about directly (YoY % for CPI/PCE, MoM change for payrolls, level for rates).
"""
from __future__ import annotations
import json
import sqlite3
import time
import requests
from dk.config import DB_PATH, get_key

_URL = "https://api.stlouisfed.org/fred/series/observations"

# id, units, label, scale, decimals, suffix, signed, impact, lean-kind
_SERIES = [
    ("CPIAUCSL",        "pc1", "CPI (YoY)",               1,     1, "%", False, "high",   "infl"),
    ("CPILFESL",        "pc1", "Core CPI (YoY)",          1,     1, "%", False, "high",   "infl"),
    ("PCEPILFE",        "pc1", "Core PCE (YoY)",          1,     1, "%", False, "high",   "infl"),
    ("PAYEMS",          "chg", "Nonfarm Payrolls (MoM)",  1,     0, "K", True,  "high",   "jobs"),
    ("UNRATE",          "lin", "Unemployment Rate",       1,     1, "%", False, "high",   "unemp"),
    ("A191RL1Q225SBEA", "lin", "Real GDP (QoQ ann.)",     1,     1, "%", True,  "high",   "growth"),
    ("RSAFS",           "pch", "Retail Sales (MoM)",      1,     1, "%", True,  "medium", "growth"),
    ("ICSA",            "lin", "Initial Jobless Claims",  0.001, 0, "K", False, "medium", "claims"),
    ("FEDFUNDS",        "lin", "Fed Funds Rate",          1,     2, "%", False, "high",   "rate"),
]

# lean-kind -> (word when latest > prev, word when latest < prev)
_LEAN = {
    "infl":   ("hotter", "cooler"),
    "jobs":   ("stronger", "weaker"),
    "unemp":  ("higher", "lower"),
    "claims": ("rising", "falling"),
    "growth": ("stronger", "weaker"),
    "rate":   ("higher", "lower"),
}

_last_fetch = 0.0  # module throttle — econ data changes at most daily


def _fmt(val, scale, decimals, suffix, signed) -> str:
    try:
        f = float(val) * scale
    except (TypeError, ValueError):
        return "—"
    sign = "+" if signed else ""
    return f"{f:{sign},.{decimals}f}{suffix}"


def _latest_two(key: str, series_id: str, units: str):
    """Return (latest, prev) observation dicts (newest first), or (None, None)."""
    try:
        r = requests.get(_URL, params={
            "series_id": series_id, "api_key": key, "file_type": "json",
            "units": units, "sort_order": "desc", "limit": 2,
        }, timeout=15)
        if r.status_code != 200:
            if r.status_code in (400, 403):
                print(f"[fred] {series_id}: HTTP {r.status_code} {r.text[:80]}")
            return None, None, r.status_code
        obs = (r.json() or {}).get("observations") or []
    except Exception as e:
        print(f"[fred] {series_id}: {e}")
        return None, None, None
    obs = [o for o in obs if o.get("value") not in (None, ".", "")]
    if len(obs) < 2:
        return None, None, 200
    return obs[0], obs[1], 200


def fetch_and_alert(throttle_seconds: int = 1800) -> dict:
    """Check each tracked FRED series; alert once per fresh release. Throttled so
    we don't re-poll monthly/weekly data every 15-min cycle."""
    global _last_fetch
    key = get_key("FRED_API_KEY")
    if not key:
        return {"configured": False, "alerts": 0}
    now = time.time()
    if now - _last_fetch < throttle_seconds:
        return {"configured": True, "skipped": "throttled"}
    _last_fetch = now

    n = 0
    with sqlite3.connect(DB_PATH) as c:
        for sid, units, label, scale, dec, suf, signed, impact, lean in _SERIES:
            latest, prev, http = _latest_two(key, sid, units)
            if http in (400, 403):  # bad key — stop, don't spam the rest
                return {"configured": True, "alerts": n, "http": http}
            if not latest or not prev:
                continue
            date = latest.get("date") or ""
            marker = f"fred::{sid}::{date}"
            if c.execute("SELECT 1 FROM alerts WHERE kind='ECON_PRINT' AND payload LIKE ? LIMIT 1",
                         (f'%"m": "{marker}"%',)).fetchone():
                continue
            try:
                a_val, p_val = float(latest["value"]), float(prev["value"])
            except (TypeError, ValueError, KeyError):
                continue
            up, down = _LEAN.get(lean, ("higher", "lower"))
            if a_val > p_val:
                arrow, note = "↑", up
            elif a_val < p_val:
                arrow, note = "↓", down
            else:
                arrow, note = "→", "flat"
            impact_icon = "🔴" if impact == "high" else "🟠"
            msg = (f"{impact_icon} 📊 {label}: {_fmt(a_val,scale,dec,suf,signed)} "
                   f"(prev {_fmt(p_val,scale,dec,suf,signed)}) {arrow} {note}")
            c.execute("INSERT INTO alerts (symbol, kind, message, payload) VALUES (?,?,?,?)",
                      (None, "ECON_PRINT", msg,
                       json.dumps({"m": marker, "series": sid, "actual": a_val,
                                   "previous": p_val, "period": date, "impact": impact,
                                   "source": "FRED"})))
            n += 1
            time.sleep(0.1)
        c.commit()
    return {"configured": True, "alerts": n, "source": "FRED"}
