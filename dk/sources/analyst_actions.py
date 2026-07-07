"""Analyst upgrades / downgrades / initiations per ticker (individual signal).

Uses Finnhub's free `stock/upgrade-downgrade` endpoint. Emits ANALYST_ACTION
alerts for recent rating changes on tracked names, deduped. No-op without a key.
"""
from __future__ import annotations
import sqlite3
import time
from dk.config import DB_PATH, get_key, equity_symbols


def _tracked(max_n: int = 45) -> list[str]:
    syms = list(equity_symbols())
    try:
        from dk.jobs.portfolio_digest import all_portfolio_tickers
        for s in all_portfolio_tickers():
            if s not in syms:
                syms.append(s)
    except Exception:
        pass
    return syms[:max_n]


def fetch_and_alert(lookback_days: int = 3) -> dict:
    key = get_key("FINNHUB_KEY")
    if not key:
        return {"configured": False, "alerts": 0}
    import requests
    cutoff = time.time() - lookback_days * 86400
    verb = {"up": "upgraded", "down": "downgraded", "init": "initiated", "main": "reiterated"}
    icon = {"up": "⬆️", "down": "⬇️", "init": "🆕", "main": "🔁"}
    n = 0
    with sqlite3.connect(DB_PATH) as c:
        for sym in _tracked():
            try:
                r = requests.get("https://finnhub.io/api/v1/stock/upgrade-downgrade",
                                 params={"symbol": sym, "token": key}, timeout=12)
                if r.status_code != 200:
                    continue
                for a in (r.json() or []):
                    gt = a.get("gradeTime", 0) or 0
                    if gt < cutoff:
                        continue
                    firm = a.get("company") or "?"
                    action = (a.get("action") or "").lower()
                    frm, to = a.get("fromGrade") or "", a.get("toGrade") or "?"
                    marker = f"analyst::{sym}::{gt}::{firm}"
                    if c.execute("SELECT 1 FROM alerts WHERE kind='ANALYST_ACTION' "
                                 "AND payload LIKE ? LIMIT 1", (f'%"m":"{marker}"%',)).fetchone():
                        continue
                    grade = f"{frm}→{to}" if frm else to
                    msg = f"{icon.get(action,'🔵')} {sym}: {firm} {verb.get(action, action or 'rated')} — {grade}"
                    import json
                    c.execute("INSERT INTO alerts (symbol, kind, message, payload) VALUES (?,?,?,?)",
                              (sym, "ANALYST_ACTION", msg,
                               json.dumps({"m": marker, "firm": firm, "action": action,
                                           "from": frm, "to": to})))
                    n += 1
                time.sleep(0.2)  # be polite to the 60/min free tier
            except Exception as e:
                print(f"[analyst] {sym}: {e}")
                continue
        c.commit()
    return {"configured": True, "alerts": n}
