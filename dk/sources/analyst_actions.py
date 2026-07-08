"""Analyst rating signal per ticker (individual signal).

Finnhub's per-firm `stock/upgrade-downgrade` and `price-target` endpoints are
PREMIUM (403 on the free tier). So instead we use Finnhub's FREE
`stock/recommendation` endpoint — the monthly analyst consensus (strongBuy / buy
/ hold / sell / strongSell counts) — and detect month-over-month SHIFTS. A rising
buy count / falling sell count = net upgrades; the reverse = net downgrades.

Emits ANALYST_ACTION alerts for meaningful consensus shifts on tracked names,
deduped once per name per monthly period. No-op without a FINNHUB_KEY.
"""
from __future__ import annotations
import json
import sqlite3
import time
from dk.config import DB_PATH, get_key, equity_symbols

_URL = "https://finnhub.io/api/v1/stock/recommendation"


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


def _consensus(row: dict):
    """Weighted mean rating (-2..+2) and total analyst count for a month row."""
    sb = row.get("strongBuy", 0) or 0
    b = row.get("buy", 0) or 0
    h = row.get("hold", 0) or 0
    s = row.get("sell", 0) or 0
    ss = row.get("strongSell", 0) or 0
    tot = sb + b + h + s + ss
    if tot == 0:
        return None, 0
    mean = (sb * 2 + b * 1 + s * -1 + ss * -2) / tot
    return mean, tot


def fetch_and_alert(min_total: int = 3, max_alerts: int = 10) -> dict:
    """Detect month-over-month analyst consensus shifts. `max_alerts` caps the
    burst per cycle so a first-run catch-up spreads across a few polls rather
    than flooding one digest."""
    key = get_key("FINNHUB_KEY")
    if not key:
        return {"configured": False, "alerts": 0}
    import requests

    n = 0
    with sqlite3.connect(DB_PATH) as c:
        for sym in _tracked():
            if n >= max_alerts:
                break
            try:
                r = requests.get(_URL, params={"symbol": sym, "token": key}, timeout=12)
                time.sleep(0.15)  # polite pacing every call — stay under 60/min free tier
                if r.status_code != 200:
                    if r.status_code in (401, 403):
                        # key/plan problem — no point hammering the rest
                        return {"configured": True, "alerts": n, "http": r.status_code,
                                "note": "recommendation endpoint denied"}
                    continue
                rows = r.json() or []
                if len(rows) < 2:
                    continue
                cur, prev = rows[0], rows[1]  # newest first
                period = cur.get("period", "")
                marker = f"analyst::{sym}::{period}"
                if c.execute("SELECT 1 FROM alerts WHERE kind='ANALYST_ACTION' "
                             "AND payload LIKE ? LIMIT 1", (f'%"m": "{marker}"%',)).fetchone():
                    continue

                cs_cur, tot_cur = _consensus(cur)
                cs_prev, tot_prev = _consensus(prev)
                if cs_cur is None or cs_prev is None or tot_cur < min_total:
                    continue

                shift = cs_cur - cs_prev
                bull_cur = (cur.get("strongBuy", 0) or 0) + (cur.get("buy", 0) or 0)
                bull_prev = (prev.get("strongBuy", 0) or 0) + (prev.get("buy", 0) or 0)
                bear_cur = (cur.get("sell", 0) or 0) + (cur.get("strongSell", 0) or 0)
                bear_prev = (prev.get("sell", 0) or 0) + (prev.get("strongSell", 0) or 0)
                hold_cur = cur.get("hold", 0) or 0
                hold_prev = prev.get("hold", 0) or 0
                d_bull, d_bear = bull_cur - bull_prev, bear_cur - bear_prev

                # Fire only on a meaningful move (avoids noise + first-run flood)
                if abs(shift) < 0.10 and abs(d_bull) < 2 and abs(d_bear) < 2:
                    continue
                if shift > 0.01:
                    icon, verb = "⬆️", "improved"
                elif shift < -0.01:
                    icon, verb = "⬇️", "weakened"
                else:
                    continue  # counts shuffled but netted flat

                msg = (f"{icon} {sym}: analyst consensus {verb} — "
                       f"{bull_cur} buy / {hold_cur} hold / {bear_cur} sell "
                       f"(was {bull_prev}/{hold_prev}/{bear_prev}, {tot_cur} analysts)")
                c.execute("INSERT INTO alerts (symbol, kind, message, payload) VALUES (?,?,?,?)",
                          (sym, "ANALYST_ACTION", msg,
                           json.dumps({"m": marker, "consensus": round(cs_cur, 2),
                                       "prev_consensus": round(cs_prev, 2),
                                       "buy": bull_cur, "hold": hold_cur, "sell": bear_cur,
                                       "analysts": tot_cur})))
                n += 1
                time.sleep(0.2)  # be polite to the 60/min free tier
            except Exception as e:
                print(f"[analyst] {sym}: {e}")
                continue
        c.commit()
    return {"configured": True, "alerts": n, "source": "finnhub-recommendation"}
