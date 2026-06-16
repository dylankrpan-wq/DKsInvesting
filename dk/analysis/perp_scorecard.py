"""Perp call-out scorecard — a persistent track record of every pushed setup.

Every SETUP_SCAN call-out (entry/stop/TP1-3) is replayed against live candles to
reconstruct what price actually did: did it reach TP1 before the stop (WIN), hit
the stop first (LOSS), or is it still working (OPEN)? Plus MFE/MAE, the highest
TP reached, and a realized-R estimate. Results are upserted into
`perp_callout_results` so resolved call-outs FREEZE (we don't re-fetch ancient
candles) and the record accumulates for accuracy review over time.

Honest by construction: outcomes are measured from candle highs/lows, never
asserted. Granularity caveat — replay uses the candle bar sized to each
call-out's age, so a fast intra-bar wick that touched a level can be missed, and
a single bar that touches BOTH stop and a TP is scored conservatively (stop-first).

Scoring model (documented so it can be changed without re-fetching — facts are
stored, metrics derived):
  - WIN  = TP1 touched strictly before the first stop touch.
  - LOSS = stop touched first (same-bar stop+TP counts as stop).
  - OPEN = neither resolved yet (and younger than max_age_hours).
  - max_tp = highest TP rung reached before the first stop.
  - realized_r: LOSS -> -1.0; WIN -> R-multiple of the highest TP reached
    (best-case "let it run to the furthest rung it actually reached"); OPEN -> None.
"""
from __future__ import annotations
import io
import json
import sys
from datetime import datetime, timezone
from dk.config import load_watchlist
from dk.store import db as store
from dk.sources import crypto_deriv

_MAX_AGE_H = 48  # past this with no resolution, freeze at whatever it reached


def _cfg() -> dict:
    return (load_watchlist().get("perp_tracker") or {})


def _fmt(p):
    from dk.analysis.perp import _fmt as f
    return f(p)


def _ensure_table(c) -> None:
    c.execute("""
        CREATE TABLE IF NOT EXISTS perp_callout_results (
            alert_id      INTEGER PRIMARY KEY,
            inst_id       TEXT,
            side          TEXT,
            entry         REAL,
            stop          REAL,
            tp1 REAL, tp2 REAL, tp3 REAL,
            rr1           REAL,
            risk_pct      REAL,
            opened_at     TEXT,
            status        TEXT,          -- WIN / LOSS / OPEN / EXPIRED
            max_tp        INTEGER,       -- 0..3 highest rung reached before stop
            tp1_win       INTEGER,       -- 1 if TP1 before stop
            stopped       INTEGER,
            ambiguous     INTEGER,       -- a bar touched both stop and a TP
            mfe_pct       REAL,
            mae_pct       REAL,
            last_price    REAL,
            cur_pct       REAL,
            realized_r    REAL,
            bar           TEXT,          -- candle bar used for replay
            resolved      INTEGER,
            resolved_at   TEXT,
            updated_at    TEXT
        )""")


def _bar_for_age(age_h: float) -> tuple[str, int]:
    """Pick the finest candle bar that still reaches back to the call-out."""
    if age_h <= 18:
        return "5m", 300       # ~25h
    if age_h <= 90:
        return "1H", 300       # ~12.5d
    if age_h <= 480:
        return "4H", 300       # ~50d
    return "1D", 300


def reconstruct(inst_id: str, side: str, entry: float, stop: float,
                tps: list[float], opened_ms: float) -> dict:
    """Measured outcome facts for one call-out (no DB)."""
    # clock reference + age
    ref = crypto_deriv.fetch_candles(inst_id, "1m", 1)
    now_ms = ref[-1]["ts"] if ref else opened_ms
    age_h = max(0.0, (now_ms - opened_ms) / 3.6e6)
    bar, limit = _bar_for_age(age_h)

    candles = crypto_deriv.fetch_candles(inst_id, bar, limit)
    last = crypto_deriv.fetch_ticker(inst_id)
    last_price = last["last"] if last else (candles[-1]["close"] if candles else entry)
    path = [c for c in candles if c["ts"] >= opened_ms]

    risk = abs(entry - stop) or 1e-9
    is_long = side == "long"
    stop_idx = None
    tp_idx = {1: None, 2: None, 3: None}
    mfe = mae = 0.0
    ambiguous = False

    for j, c in enumerate(path):
        fav = (c["high"] - entry) / entry * 100 if is_long else (entry - c["low"]) / entry * 100
        adv = (c["low"] - entry) / entry * 100 if is_long else (entry - c["high"]) / entry * 100
        mfe = max(mfe, fav)
        mae = min(mae, adv)
        hit_stop = (c["low"] <= stop) if is_long else (c["high"] >= stop)
        if hit_stop and stop_idx is None:
            stop_idx = j
        for i, lv in enumerate(tps, 1):
            if lv and tp_idx[i] is None:
                hit_tp = (c["high"] >= lv) if is_long else (c["low"] <= lv)
                if hit_tp:
                    tp_idx[i] = j
                    if j == stop_idx:
                        ambiguous = True

    def before_stop(i: int) -> bool:
        if tp_idx[i] is None:
            return False
        return stop_idx is None or tp_idx[i] < stop_idx  # same bar -> stop-first

    max_tp = max((i for i in (1, 2, 3) if before_stop(i)), default=0)
    tp1_win = before_stop(1)
    stopped = stop_idx is not None

    cur_pct = ((last_price - entry) if is_long else (entry - last_price)) / entry * 100

    if max_tp >= 1:
        status = "WIN"
        realized_r = round(abs(tps[max_tp - 1] - entry) / risk, 2)
    elif stopped:
        status = "LOSS"
        realized_r = -1.0
    else:
        status = "OPEN"
        realized_r = None

    # Resolution: full target (TP3) or stopped => done. Else open, unless aged out.
    resolved = (max_tp == 3) or stopped
    if not resolved and age_h >= _MAX_AGE_H:
        status = "EXPIRED"
        resolved = True
        realized_r = (round(abs(tps[max_tp - 1] - entry) / risk, 2) if max_tp >= 1 else 0.0)

    return {
        "status": status, "max_tp": max_tp, "tp1_win": int(tp1_win),
        "stopped": int(stopped), "ambiguous": int(ambiguous),
        "mfe_pct": round(mfe, 2), "mae_pct": round(mae, 2),
        "last_price": last_price, "cur_pct": round(cur_pct, 2),
        "realized_r": realized_r, "bar": bar, "age_h": round(age_h, 1),
        "resolved": int(resolved),
    }


def _callouts(c) -> list:
    """All call-outs (pushed SETUP_SCAN + silently-tracked SETUP_TRACK) with
    parsed payloads + captured features, oldest first. `pushed` flags the ones
    that actually went to the phone vs. the wider research-tracked set."""
    rows = c.execute(
        "SELECT id, symbol, kind, payload, created_at FROM alerts "
        "WHERE kind IN ('SETUP_SCAN','SETUP_TRACK') ORDER BY created_at").fetchall()
    out = []
    for r in rows:
        try:
            p = json.loads(r["payload"]) if r["payload"] else {}
        except Exception:
            p = {}
        if not p.get("entry") or not p.get("stop"):
            continue
        out.append({"alert_id": r["id"], "inst_id": p.get("inst_id") or r["symbol"],
                    "side": p.get("side"), "entry": p["entry"], "stop": p["stop"],
                    "tps": [t.get("level") for t in (p.get("tps") or [])],
                    "rr1": p.get("rr1"), "risk_pct": p.get("risk_pct"),
                    "opened_at": r["created_at"],
                    "pushed": 1 if r["kind"] == "SETUP_SCAN" else 0,
                    # features for win/loss bucket analysis
                    "phase": p.get("phase"), "funding_tailwind": int(bool(p.get("funding_tailwind"))),
                    "off_high_pct": p.get("off_high_pct"), "atr_pct": p.get("atr_pct"),
                    "vs_ma_pct": p.get("vs_ma_pct"), "last_vol_x": p.get("last_vol_x")})
    return out


def build_ledger(refresh_resolved: bool = False, push_outcomes: bool = False) -> list[dict]:
    """Reconstruct every call-out, upsert results. Resolved rows are reused
    (frozen) unless refresh_resolved=True. Returns the full result list."""
    store.init_db()
    with store.conn() as c:
        _ensure_table(c)
        cached = {row["alert_id"]: dict(row)
                  for row in c.execute("SELECT * FROM perp_callout_results").fetchall()}
        callouts = _callouts(c)

    results: list[dict] = []
    to_write: list[dict] = []
    for co in callouts:
        prev = cached.get(co["alert_id"])
        if prev and prev.get("resolved") and not refresh_resolved:
            # merge: outcome from the frozen cached row, features from the alert
            # payload (the cached row predates the feature columns), pushed flag too
            results.append({**co, **prev})
            continue
        opened_ms = datetime.fromisoformat(co["opened_at"]).replace(
            tzinfo=timezone.utc).timestamp() * 1000
        tps = (co["tps"] + [None, None, None])[:3]
        oc = reconstruct(co["inst_id"], co["side"], co["entry"], co["stop"], tps, opened_ms)
        rec = {**co, **oc, "tp1": tps[0], "tp2": tps[1], "tp3": tps[2]}
        results.append(rec)
        to_write.append(rec)

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with store.conn() as c:
        _ensure_table(c)
        for r in to_write:
            c.execute("""
                INSERT INTO perp_callout_results
                  (alert_id, inst_id, side, entry, stop, tp1, tp2, tp3, rr1, risk_pct,
                   opened_at, status, max_tp, tp1_win, stopped, ambiguous, mfe_pct,
                   mae_pct, last_price, cur_pct, realized_r, bar, resolved, resolved_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(alert_id) DO UPDATE SET
                   status=excluded.status, max_tp=excluded.max_tp, tp1_win=excluded.tp1_win,
                   stopped=excluded.stopped, ambiguous=excluded.ambiguous, mfe_pct=excluded.mfe_pct,
                   mae_pct=excluded.mae_pct, last_price=excluded.last_price, cur_pct=excluded.cur_pct,
                   realized_r=excluded.realized_r, bar=excluded.bar, resolved=excluded.resolved,
                   resolved_at=excluded.resolved_at, updated_at=excluded.updated_at""",
                (r["alert_id"], r["inst_id"], r["side"], r["entry"], r["stop"],
                 r["tp1"], r["tp2"], r["tp3"], r.get("rr1"), r.get("risk_pct"),
                 r["opened_at"], r["status"], r["max_tp"], r["tp1_win"], r["stopped"],
                 r["ambiguous"], r["mfe_pct"], r["mae_pct"], r["last_price"], r["cur_pct"],
                 r["realized_r"], r["bar"], r["resolved"],
                 (now if r["resolved"] else None), now))
    return results


def summary(rows: list[dict]) -> dict:
    n = len(rows)
    resolved = [r for r in rows if r.get("status") in ("WIN", "LOSS", "EXPIRED")]
    wins = [r for r in rows if r.get("status") == "WIN"]
    losses = [r for r in rows if r.get("status") == "LOSS"]
    open_ = [r for r in rows if r.get("status") == "OPEN"]
    decided = [r for r in rows if r.get("status") in ("WIN", "LOSS")]
    rr = [r["realized_r"] for r in rows if r.get("realized_r") is not None]
    win_rate = (len(wins) / len(decided) * 100) if decided else None
    avg_mfe = (sum(r["mfe_pct"] for r in rows) / n) if n else 0
    avg_mae = (sum(r["mae_pct"] for r in rows) / n) if n else 0
    expectancy = (sum(rr) / len(rr)) if rr else None
    return {
        "total": n, "resolved": len(resolved), "open": len(open_),
        "wins": len(wins), "losses": len(losses),
        "win_rate_pct": round(win_rate, 1) if win_rate is not None else None,
        "avg_mfe_pct": round(avg_mfe, 2), "avg_mae_pct": round(avg_mae, 2),
        "expectancy_r": round(expectancy, 2) if expectancy is not None else None,
        "total_r": round(sum(rr), 2) if rr else 0.0,
        "pushed": sum(1 for r in rows if r.get("pushed")),
        "tracked": sum(1 for r in rows if not r.get("pushed")),
    }


def _band(v, edges):
    """Map a value to a labeled band. edges = [(upper, label), ...]; an upper of
    None is the catch-all top band. Returns None if v is None."""
    if v is None:
        return None
    for upper, label in edges:
        if upper is None or v < upper:
            return label
    return None


def _grp_stats(g: list[dict]) -> dict:
    decided = [r for r in g if r.get("status") in ("WIN", "LOSS")]
    wins = sum(1 for r in decided if r["status"] == "WIN")
    rr = [r["realized_r"] for r in g if r.get("realized_r") is not None]
    return {
        "n": len(g),
        "win_rate": round(wins / len(decided) * 100, 1) if decided else None,
        "exp": round(sum(rr) / len(rr), 2) if rr else None,
        "total_r": round(sum(rr), 1) if rr else 0.0,
    }


def feature_report(rows: list[dict]) -> str:
    """Bucket resolved call-outs by feature → win-rate / expectancy / total R, so
    we can see which conditions actually predict winners and tighten the live
    push criteria on evidence (not vibes)."""
    res = [r for r in rows if r.get("status") in ("WIN", "LOSS", "EXPIRED")]
    if len(res) < 4:
        return ("_Feature analysis needs more resolved call-outs (have "
                f"{len(res)}). It fills in as the tracked sample grows._")
    dims = [
        ("Side", lambda r: r.get("side")),
        ("Funding", lambda r: "tailwind" if r.get("funding_tailwind") else "neutral/against"),
        ("R:R (rr1)", lambda r: _band(r.get("rr1"), [(3, "<3"), (5, "3-5"), (None, "5+")])),
        ("Risk %", lambda r: _band(r.get("risk_pct"), [(1, "<1%"), (2, "1-2%"), (None, "2%+")])),
        ("1H ATR %", lambda r: _band(r.get("atr_pct"), [(3, "<3%"), (8, "3-8%"), (None, "8%+")])),
        ("Phase", lambda r: r.get("phase")),
    ]
    L = ["**🔬 What's winning — feature breakdown** (resolved call-outs, best buckets first)", ""]
    for name, fn in dims:
        groups: dict = {}
        for r in res:
            k = fn(r)
            if k is None:
                continue
            groups.setdefault(k, []).append(r)
        if not groups:
            continue
        L.append(f"**{name}**")
        L.append("| bucket | n | win% | exp R | total R |")
        L.append("|---|--:|--:|--:|--:|")
        for k, g in sorted(groups.items(), key=lambda kv: -(_grp_stats(kv[1])["exp"] or -99)):
            s = _grp_stats(g)
            wr = f"{s['win_rate']}%" if s["win_rate"] is not None else "—"
            ex = f"{s['exp']:+}" if s["exp"] is not None else "—"
            L.append(f"| {k} | {s['n']} | {wr} | {ex} | {s['total_r']:+} |")
        L.append("")
    L.append("_Sorted by expectancy. Small samples are noisy — let counts build before tightening filters._")
    return "\n".join(L)


def render_markdown(rows: list[dict], stats: dict) -> str:
    icon = {"WIN": "✅", "LOSS": "🛑", "OPEN": "⏳", "EXPIRED": "⌛"}
    L = ["**📋 Perp call-out scorecard** — every pushed setup, replayed vs live candles.",
         ""]
    wr = f"{stats['win_rate_pct']}%" if stats["win_rate_pct"] is not None else "—"
    exp = f"{stats['expectancy_r']:+}R" if stats["expectancy_r"] is not None else "—"
    L.append(f"**{stats['total']} call-outs** "
             f"({stats.get('pushed', 0)} pushed · {stats.get('tracked', 0)} tracked) · "
             f"{stats['wins']}W / {stats['losses']}L / {stats['open']} open · "
             f"win-rate {wr} (of decided) · expectancy {exp} · total {stats['total_r']:+}R")
    L.append(f"avg MFE {stats['avg_mfe_pct']:+}% · avg MAE {stats['avg_mae_pct']:+}%")
    L += ["", "| When (UTC) | Pair | Side | Status | MaxTP | MFE | MAE | Now | Real R |",
          "|---|---|---|---|---|---|---|---|---|"]
    for r in sorted(rows, key=lambda x: x["opened_at"], reverse=True):
        st = f"{icon.get(r['status'],'')} {r['status']}"
        mt = f"TP{r['max_tp']}" if r["max_tp"] else "—"
        rr = f"{r['realized_r']:+}" if r.get("realized_r") is not None else f"{r['cur_pct']:+.1f}%*"
        amb = "⚠️" if r.get("ambiguous") else ""
        L.append(f"| {r['opened_at'][5:16]} | {r['inst_id']} | {r['side']} | {st}{amb} | "
                 f"{mt} | {r['mfe_pct']:+.1f}% | {r['mae_pct']:+.1f}% | "
                 f"{r['cur_pct']:+.1f}% | {rr} |")
    L += ["", "_Real R: realized for WIN/LOSS; `*` = current unrealized % for open. "
          "⚠️ = one bar touched both stop and a TP (scored stop-first). Replay granularity "
          "= per-call-out candle bar; fast wicks can be missed. Discovery track record, not advice._"]
    return "\n".join(L)


def backfill_tracker() -> dict:
    """Register every still-OPEN call-out into the live tracker (perp_signals) so
    TP/stop pings + the hourly recap resume watching them. Idempotent."""
    from dk.analysis import perp_tracker
    rows = build_ledger()
    registered, skipped = [], []
    with store.conn() as c:
        for r in rows:
            if r.get("status") != "OPEN":
                continue
            payload = {"inst_id": r["inst_id"], "side": r["side"], "entry": r["entry"],
                       "stop": r["stop"],
                       "tps": [{"level": r[k]} for k in ("tp1", "tp2", "tp3") if r.get(k)]}
            ok = perp_tracker.register_signal(r["alert_id"], payload)
            (registered if ok else skipped).append(r["inst_id"])
    return {"registered": registered, "skipped": skipped}


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    rows = build_ledger(refresh_resolved=True)
    print(render_markdown(rows, summary(rows)))
    print("\n" + feature_report(rows))
