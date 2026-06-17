"""Equity idea scorecard — a persistent track record of every equity idea.

Replays each EQUITY_IDEA (phone-pushed) and EQUITY_IDEA_TRACK (silently tracked)
against DAILY candles to reconstruct what price did: reached TP1 before the stop
(WIN), hit the stop first (LOSS), or still working (OPEN). Plus MFE/MAE, highest
TP reached, and realized R. Results freeze in `equity_idea_results` so the record
accumulates — and we can ask the question that matters: which HORIZON and which
setups actually pay (do long-term holds beat swings?), so the push bar tightens
on evidence.

Long-only (every equity idea is a long). Daily-bar granularity, so a fast intra-
day round-trip can be missed and a single day touching BOTH stop and a TP is
scored conservatively (stop-first). Honest by construction — outcomes measured
from candle highs/lows, never asserted.
"""
from __future__ import annotations
import io
import json
import sqlite3
import sys
from datetime import date, datetime, timezone
from dk.config import DB_PATH
from dk.store import db as store
from dk.sources import prices_yfinance

# Per-horizon patience before an unresolved idea is frozen EXPIRED.
_MAX_AGE_DAYS = {"short_term": 21, "swing": 75, "long_term": 300}


def _fmt(p):
    from dk.analysis.perp import _fmt as f
    return f(p)


def _daily_bars(symbol: str, since: str) -> list[dict]:
    """Daily OHLC from the prices table on/after `since` (a YYYY-MM-DD date), oldest first."""
    with sqlite3.connect(DB_PATH) as c:
        rows = c.execute(
            """SELECT ts, high, low, close FROM prices
               WHERE symbol=? AND ts >= ? AND high IS NOT NULL AND low IS NOT NULL
                 AND close IS NOT NULL
               ORDER BY ts ASC""", (symbol, since)).fetchall()
    return [{"ts": r[0], "high": float(r[1]), "low": float(r[2]), "close": float(r[3])}
            for r in rows]


def reconstruct(symbol: str, entry: float, stop: float, targets: list[float],
                opened_at: str, horizon: str) -> dict:
    """Measured outcome facts for one long idea from daily bars (no DB write)."""
    opened_date = (opened_at or "")[:10]
    bars = _daily_bars(symbol, opened_date)
    last_price = bars[-1]["close"] if bars else entry
    risk = abs(entry - stop) or 1e-9
    tps = [t for t in (targets or []) if t]

    stop_idx = None
    tp_idx: dict[int, int] = {}
    mfe = mae = 0.0
    for j, b in enumerate(bars):
        mfe = max(mfe, (b["high"] - entry) / entry * 100)
        mae = min(mae, (b["low"] - entry) / entry * 100)
        if b["low"] <= stop and stop_idx is None:
            stop_idx = j
        for i, lv in enumerate(tps, 1):
            if i not in tp_idx and b["high"] >= lv:
                tp_idx[i] = j

    def before_stop(i: int) -> bool:
        if i not in tp_idx:
            return False
        return stop_idx is None or tp_idx[i] < stop_idx  # same bar -> stop-first

    max_tp = max((i for i in range(1, len(tps) + 1) if before_stop(i)), default=0)
    stopped = stop_idx is not None
    cur_pct = (last_price - entry) / entry * 100 if entry else 0.0

    if max_tp >= 1:
        status, realized_r = "WIN", round(abs(tps[max_tp - 1] - entry) / risk, 2)
    elif stopped:
        status, realized_r = "LOSS", -1.0
    else:
        status, realized_r = "OPEN", None

    resolved = (len(tps) > 0 and max_tp == len(tps)) or stopped
    try:
        age_days = (date.today() - date.fromisoformat(opened_date)).days
    except Exception:
        age_days = 0
    if not resolved and age_days >= _MAX_AGE_DAYS.get(horizon, 90):
        status, resolved = "EXPIRED", True
        realized_r = round(abs(tps[max_tp - 1] - entry) / risk, 2) if max_tp >= 1 else 0.0

    return {"status": status, "max_tp": max_tp, "stopped": int(stopped),
            "mfe_pct": round(mfe, 2), "mae_pct": round(mae, 2),
            "last_price": round(last_price, 4), "cur_pct": round(cur_pct, 2),
            "realized_r": realized_r, "resolved": int(resolved), "age_days": age_days}


def _callouts(c) -> list[dict]:
    """Every equity idea (pushed + tracked) with parsed payload + features."""
    rows = c.execute(
        "SELECT id, symbol, kind, payload, created_at FROM alerts "
        "WHERE kind IN ('EQUITY_IDEA','EQUITY_IDEA_TRACK') ORDER BY created_at").fetchall()
    out = []
    for r in rows:
        try:
            p = json.loads(r["payload"]) if r["payload"] else {}
        except Exception:
            p = {}
        if not p.get("entry") or not p.get("stop"):
            continue
        tgts = [t for t in (p.get("targets") or []) if t]
        out.append({"alert_id": r["id"], "symbol": p.get("symbol") or r["symbol"],
                    "horizon": p.get("horizon"), "pushed": 1 if r["kind"] == "EQUITY_IDEA" else 0,
                    "entry": p["entry"], "stop": p["stop"], "targets": tgts,
                    "tp1": tgts[0] if len(tgts) > 0 else None,
                    "tp2": tgts[1] if len(tgts) > 1 else None,
                    "tp3": tgts[2] if len(tgts) > 2 else None,
                    "rr1": p.get("rr1"), "opened_at": r["created_at"],
                    "cap": p.get("cap"), "conviction": p.get("conviction"),
                    "rs120": p.get("rs120")})
    return out


def build_ledger(refresh_resolved: bool = False, max_refresh: int = 30) -> list[dict]:
    """Replay every idea, upsert results (resolved rows frozen unless
    refresh_resolved). Refreshes the daily history of up to max_refresh distinct
    unresolved symbols first so open ideas can actually resolve over time."""
    store.init_db()
    with store.conn() as c:
        cached = {row["alert_id"]: dict(row)
                  for row in c.execute("SELECT * FROM equity_idea_results").fetchall()}
        callouts = _callouts(c)

    # Refresh daily bars for unresolved symbols (capped, distinct) so resolution
    # isn't stuck on stale prices for names not otherwise being re-fetched.
    need = []
    for co in callouts:
        prev = cached.get(co["alert_id"])
        if refresh_resolved or not (prev and prev.get("resolved")):
            need.append(co["symbol"])
    seen: set[str] = set()
    for sym in need:
        if len(seen) >= max_refresh:
            break
        if sym in seen:
            continue
        seen.add(sym)
        try:
            prices_yfinance.fetch_prices(sym, period="6mo")
        except Exception as e:
            print(f"[equity_scorecard] refresh {sym}: {e}")

    results: list[dict] = []
    to_write: list[dict] = []
    for co in callouts:
        prev = cached.get(co["alert_id"])
        if prev and prev.get("resolved") and not refresh_resolved:
            results.append({**co, **prev})  # frozen outcome + payload features
            continue
        oc = reconstruct(co["symbol"], co["entry"], co["stop"], co["targets"],
                         co["opened_at"], co["horizon"])
        results.append({**co, **oc})
        to_write.append({**co, **oc})

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with store.conn() as c:
        for r in to_write:
            c.execute("""
                INSERT INTO equity_idea_results
                  (alert_id, symbol, horizon, pushed, entry, stop, tp1, tp2, tp3, rr1,
                   opened_at, status, max_tp, stopped, mfe_pct, mae_pct, last_price,
                   cur_pct, realized_r, resolved, resolved_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(alert_id) DO UPDATE SET
                   status=excluded.status, max_tp=excluded.max_tp, stopped=excluded.stopped,
                   mfe_pct=excluded.mfe_pct, mae_pct=excluded.mae_pct,
                   last_price=excluded.last_price, cur_pct=excluded.cur_pct,
                   realized_r=excluded.realized_r, resolved=excluded.resolved,
                   resolved_at=excluded.resolved_at, updated_at=excluded.updated_at""",
                (r["alert_id"], r["symbol"], r["horizon"], r["pushed"], r["entry"], r["stop"],
                 r["tp1"], r["tp2"], r["tp3"], r.get("rr1"), r["opened_at"], r["status"],
                 r["max_tp"], r["stopped"], r["mfe_pct"], r["mae_pct"], r["last_price"],
                 r["cur_pct"], r["realized_r"], r["resolved"],
                 (now if r["resolved"] else None), now))
    return results


def summary(rows: list[dict]) -> dict:
    n = len(rows)
    wins = [r for r in rows if r.get("status") == "WIN"]
    losses = [r for r in rows if r.get("status") == "LOSS"]
    open_ = [r for r in rows if r.get("status") == "OPEN"]
    decided = [r for r in rows if r.get("status") in ("WIN", "LOSS")]
    rr = [r["realized_r"] for r in rows if r.get("realized_r") is not None]
    win_rate = (len(wins) / len(decided) * 100) if decided else None
    expectancy = (sum(rr) / len(rr)) if rr else None
    return {
        "total": n, "resolved": len([r for r in rows if r.get("status") in ("WIN", "LOSS", "EXPIRED")]),
        "open": len(open_), "wins": len(wins), "losses": len(losses),
        "win_rate_pct": round(win_rate, 1) if win_rate is not None else None,
        "expectancy_r": round(expectancy, 2) if expectancy is not None else None,
        "total_r": round(sum(rr), 2) if rr else 0.0,
        "pushed": sum(1 for r in rows if r.get("pushed")),
        "tracked": sum(1 for r in rows if not r.get("pushed")),
    }


def horizon_report(rows: list[dict]) -> str:
    """Win-rate / expectancy / total-R bucketed by horizon — the headline question."""
    res = [r for r in rows if r.get("status") in ("WIN", "LOSS", "EXPIRED")]
    if not res:
        return "_No resolved equity ideas yet — the horizon breakdown fills in as ideas resolve._"
    order = ["short_term", "swing", "long_term"]
    L = ["**By horizon** (resolved ideas):", "",
         "| horizon | n | win% | exp R | total R |", "|---|--:|--:|--:|--:|"]
    groups: dict[str, list] = {}
    for r in res:
        groups.setdefault(r.get("horizon") or "?", []).append(r)
    for hz in order + [k for k in groups if k not in order]:
        g = groups.get(hz)
        if not g:
            continue
        decided = [r for r in g if r.get("status") in ("WIN", "LOSS")]
        w = sum(1 for r in decided if r["status"] == "WIN")
        rr = [r["realized_r"] for r in g if r.get("realized_r") is not None]
        wr = f"{round(w / len(decided) * 100, 1)}%" if decided else "—"
        ex = f"{round(sum(rr) / len(rr), 2):+}" if rr else "—"
        L.append(f"| {hz} | {len(g)} | {wr} | {ex} | {round(sum(rr), 1):+} |")
    return "\n".join(L)


def render_markdown(rows: list[dict], stats: dict) -> str:
    icon = {"WIN": "✅", "LOSS": "🛑", "OPEN": "⏳", "EXPIRED": "⌛"}
    wr = f"{stats['win_rate_pct']}%" if stats["win_rate_pct"] is not None else "—"
    exp = f"{stats['expectancy_r']:+}R" if stats["expectancy_r"] is not None else "—"
    L = ["**💡 Equity idea scorecard** — every idea (pushed + tracked), replayed vs daily candles.",
         "",
         f"**{stats['total']} ideas** ({stats['pushed']} pushed · {stats['tracked']} tracked) · "
         f"{stats['wins']}W / {stats['losses']}L / {stats['open']} open · "
         f"win-rate {wr} (of decided) · expectancy {exp} · total {stats['total_r']:+}R",
         "", horizon_report(rows), "",
         "| When | Sym | Hzn | Status | MaxTP | MFE | MAE | Now | Real R |",
         "|---|---|---|---|---|---|---|---|---|"]
    for r in sorted(rows, key=lambda x: x.get("opened_at") or "", reverse=True)[:40]:
        st = f"{icon.get(r['status'], '')} {r['status']}"
        mt = f"TP{r['max_tp']}" if r.get("max_tp") else "—"
        rr = f"{r['realized_r']:+}" if r.get("realized_r") is not None else f"{r.get('cur_pct', 0):+.1f}%*"
        hz = {"short_term": "ST", "swing": "SW", "long_term": "LT"}.get(r.get("horizon"), "?")
        tag = "" if r.get("pushed") else " ·t"
        L.append(f"| {(r.get('opened_at') or '')[5:10]} | {r['symbol']}{tag} | {hz} | {st} | "
                 f"{mt} | {r.get('mfe_pct', 0):+.1f}% | {r.get('mae_pct', 0):+.1f}% | "
                 f"{r.get('cur_pct', 0):+.1f}% | {rr} |")
    L += ["", "_`·t` = silently tracked (not pushed). Real R: realized for WIN/LOSS; `*` = "
          "current unrealized % for open. Daily-bar replay — fast intraday round-trips can be "
          "missed; same-day stop+TP scored stop-first. Track record, not advice._"]
    return "\n".join(L)


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    rows = build_ledger(refresh_resolved=True)
    print(render_markdown(rows, summary(rows)))
