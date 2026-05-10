"""Evaluator for user-defined custom alerts."""
from __future__ import annotations
import sqlite3
import json
from dk.config import DB_PATH
from dk.indicators import ta as ta_mod


def evaluate() -> int:
    """Check every active custom alert. Fire matching ones into the alerts table.
    Returns count of newly-fired alerts."""
    fired = 0
    with sqlite3.connect(DB_PATH) as c:
        c.row_factory = sqlite3.Row
        rules = c.execute(
            "SELECT id, symbol, kind, threshold, note FROM custom_alerts WHERE active=1 AND fired_at IS NULL"
        ).fetchall()

        for rule in rules:
            sym = rule["symbol"].upper()
            kind = rule["kind"]
            thr = rule["threshold"]
            triggered = False
            value = None

            if kind in ("price_above", "price_below"):
                row = c.execute(
                    "SELECT close FROM prices WHERE symbol=? ORDER BY ts DESC LIMIT 1",
                    (sym,),
                ).fetchone()
                if row and row[0] is not None:
                    value = float(row[0])
                    triggered = (kind == "price_above" and value > thr) or \
                                (kind == "price_below" and value < thr)

            elif kind in ("rsi_above", "rsi_below"):
                snap = ta_mod.compute(sym)
                if snap.rsi14 is not None:
                    value = snap.rsi14
                    triggered = (kind == "rsi_above" and value > thr) or \
                                (kind == "rsi_below" and value < thr)

            elif kind in ("sentiment_above", "sentiment_below"):
                row = c.execute(
                    """SELECT AVG(sentiment) FROM news WHERE symbol=? AND sentiment IS NOT NULL
                       AND fetched_at >= datetime('now', '-1 day')""",
                    (sym,),
                ).fetchone()
                if row and row[0] is not None:
                    value = float(row[0])
                    triggered = (kind == "sentiment_above" and value > thr) or \
                                (kind == "sentiment_below" and value < thr)

            if triggered:
                msg = f"{sym} {kind.replace('_', ' ')} {thr} (now {value:.2f})"
                if rule["note"]:
                    msg += f" — {rule['note']}"
                c.execute(
                    "INSERT INTO alerts (symbol, kind, message, payload) VALUES (?, ?, ?, ?)",
                    (sym, "CUSTOM", msg,
                     json.dumps({"rule_id": rule["id"], "kind": kind, "threshold": thr, "value": value})),
                )
                c.execute("UPDATE custom_alerts SET fired_at=CURRENT_TIMESTAMP WHERE id=?",
                          (rule["id"],))
                fired += 1
        c.commit()
    return fired
