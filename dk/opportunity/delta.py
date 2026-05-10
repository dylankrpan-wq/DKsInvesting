"""Rank/score delta detection between current and prior snapshots.

Emits:
  RANK_JUMP   — ticker climbs >= N ranks AND current score >= MIN_SCORE
  RANK_DROP   — ticker falls >= N ranks (informational)
  SCORE_SURGE — score increases by >= POINTS since prior snapshot
  NEW_TOP     — ticker enters top K from outside top K
"""
from __future__ import annotations
import json
import sqlite3
from datetime import datetime, timezone
from dk.config import DB_PATH, load_watchlist
from dk.opportunity.score import rank_all
from dk.store import db as store


DEFAULTS = {
    "rank_jump_threshold": 3,
    "rank_jump_min_score": 35.0,
    "score_surge_points": 10.0,
    "new_top_k": 5,
}


def _cfg() -> dict:
    wl = load_watchlist()
    user = (wl.get("opportunity") or {})
    return {**DEFAULTS, **{k: user[k] for k in DEFAULTS if k in user}}


def _prior_snapshot(c) -> tuple[str | None, dict[str, dict]]:
    """Return (snapshot_ts, {symbol: row}) for the most recent prior snapshot."""
    row = c.execute(
        "SELECT snapshot_ts FROM score_history ORDER BY snapshot_ts DESC LIMIT 1"
    ).fetchone()
    if not row:
        return None, {}
    ts = row[0]
    rows = c.execute(
        "SELECT symbol, rank, score FROM score_history WHERE snapshot_ts=?",
        (ts,),
    ).fetchall()
    return ts, {r[0]: {"rank": r[1], "score": r[2]} for r in rows}


def snapshot_and_alert() -> dict:
    """Compute current ranking, diff vs prior snapshot, persist new snapshot, emit alerts."""
    cfg = _cfg()
    ranked = rank_all()
    if not ranked:
        return {"snapshotted": 0, "new_alerts": 0}

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    new_alerts = 0
    discoveries: list[str] = []

    with sqlite3.connect(DB_PATH) as c:
        prior_ts, prior = _prior_snapshot(c)

        # Emit alerts based on diff
        for i, r in enumerate(ranked):
            sym = r["symbol"]
            cur_rank = i + 1
            cur_score = r["score"]
            old = prior.get(sym)
            if not old:
                continue
            rank_chg = old["rank"] - cur_rank   # positive = climbed
            score_chg = cur_score - old["score"]

            if (rank_chg >= cfg["rank_jump_threshold"]
                    and cur_score >= cfg["rank_jump_min_score"]):
                payload = {"prior_rank": old["rank"], "rank": cur_rank,
                           "score": cur_score, "score_chg": score_chg}
                msg = (f"{sym} jumped {rank_chg} ranks "
                       f"(#{old['rank']}→#{cur_rank}, score {cur_score:.1f}, {score_chg:+.1f})")
                store.add_alert(sym, "RANK_JUMP", msg, json.dumps(payload))
                new_alerts += 1
                discoveries.append(f"▲{rank_chg} {sym}: #{old['rank']}→#{cur_rank} (score {cur_score:.1f})")

            if score_chg >= cfg["score_surge_points"]:
                payload = {"score_chg": score_chg, "score": cur_score}
                msg = f"{sym} score surge {score_chg:+.1f} points (now {cur_score:.1f})"
                store.add_alert(sym, "SCORE_SURGE", msg, json.dumps(payload))
                new_alerts += 1

            # Entered top K from outside
            if cur_rank <= cfg["new_top_k"] and old["rank"] > cfg["new_top_k"]:
                payload = {"prior_rank": old["rank"], "rank": cur_rank, "score": cur_score}
                msg = f"{sym} entered top {cfg['new_top_k']} (#{old['rank']}→#{cur_rank})"
                store.add_alert(sym, "NEW_TOP", msg, json.dumps(payload))
                new_alerts += 1

        # Persist current snapshot
        store.insert_score_snapshot(now, ranked)

    return {
        "snapshotted": len(ranked),
        "snapshot_ts": now,
        "prior_ts": prior_ts,
        "new_alerts": new_alerts,
        "discoveries": discoveries,
    }


def get_with_deltas(limit_hours: float | None = None) -> list[dict]:
    """Return current ranking enriched with prior_rank and score_chg fields."""
    ranked = rank_all()
    with sqlite3.connect(DB_PATH) as c:
        # Pick prior snapshot (the most recent that's NOT the one we just wrote, if same poll wrote one)
        rows = c.execute(
            "SELECT DISTINCT snapshot_ts FROM score_history ORDER BY snapshot_ts DESC LIMIT 2"
        ).fetchall()
        prior_ts = rows[1][0] if len(rows) >= 2 else (rows[0][0] if rows else None)
        prior: dict[str, dict] = {}
        if prior_ts:
            for r in c.execute(
                "SELECT symbol, rank, score FROM score_history WHERE snapshot_ts=?",
                (prior_ts,),
            ):
                prior[r[0]] = {"rank": r[1], "score": r[2]}

    out = []
    for i, r in enumerate(ranked):
        old = prior.get(r["symbol"], {})
        rank_now = i + 1
        out.append({
            **r,
            "rank": rank_now,
            "prior_rank": old.get("rank"),
            "rank_chg": (old["rank"] - rank_now) if old else None,
            "score_chg": (r["score"] - old["score"]) if old else None,
        })
    return out


def daily_discoveries(limit: int = 6) -> list[dict]:
    """Pull today's most interesting movers — ranks that climbed most in last 24h."""
    cutoff = "datetime('now', '-26 hours')"
    with sqlite3.connect(DB_PATH) as c:
        c.row_factory = sqlite3.Row
        rows = c.execute(f"""
            WITH recent AS (
                SELECT symbol, snapshot_ts, rank, score,
                       ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY snapshot_ts DESC) AS rn
                FROM score_history
                WHERE snapshot_ts >= {cutoff}
            )
            SELECT cur.symbol,
                   cur.rank AS rank_now, prv.rank AS rank_then,
                   cur.score AS score_now, prv.score AS score_then,
                   (prv.rank - cur.rank) AS rank_chg,
                   (cur.score - prv.score) AS score_chg
            FROM recent cur
            JOIN recent prv ON prv.symbol = cur.symbol AND prv.rn > cur.rn
            WHERE cur.rn = 1
            GROUP BY cur.symbol
            ORDER BY rank_chg DESC, score_chg DESC
            LIMIT ?
        """, (limit,)).fetchall()
        return [dict(r) for r in rows]
