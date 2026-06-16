"""End-of-day digest generator — synthesizes today's signals into prose."""
from __future__ import annotations
import sqlite3
from datetime import date
from dk.config import DB_PATH


def build() -> str:
    today = date.today().isoformat()
    sections: list[str] = []

    with sqlite3.connect(DB_PATH) as c:
        c.row_factory = sqlite3.Row

        # Macro snapshot
        macro = c.execute("SELECT symbol, label, chg_pct FROM macro_context").fetchall()
        if macro:
            risk_words = []
            for m in macro:
                if m["chg_pct"] is None:  # skip rows with no change yet (mirrors hourly pulse)
                    continue
                arrow = "▲" if m["chg_pct"] >= 0 else "▼"
                risk_words.append(f"{m['label']} {arrow}{abs(m['chg_pct']):.2f}%")
            if risk_words:
                sections.append("**Macro tape** — " + " · ".join(risk_words))

        # Top movers (rank delta)
        movers = c.execute("""
            SELECT cur.symbol,
                   cur.rank cr, cur.score cs,
                   prv.rank pr, prv.score ps,
                   (prv.rank - cur.rank) AS rank_chg,
                   (cur.score - prv.score) AS score_chg
            FROM score_history cur
            JOIN score_history prv ON prv.symbol = cur.symbol
            WHERE cur.snapshot_ts = (SELECT MAX(snapshot_ts) FROM score_history)
              AND prv.snapshot_ts = (
                  SELECT MAX(snapshot_ts) FROM score_history
                   WHERE snapshot_ts < (SELECT MAX(snapshot_ts) FROM score_history)
              )
            ORDER BY ABS(rank_chg) DESC, ABS(score_chg) DESC
            LIMIT 5
        """).fetchall()
        if movers:
            lines = []
            for m in movers:
                if m["rank_chg"] > 0:
                    lines.append(f"`{m['symbol']}` ▲{m['rank_chg']} ranks (#{m['pr']}→#{m['cr']}, score {m['ps']:.1f}→{m['cs']:.1f})")
                elif m["rank_chg"] < 0:
                    lines.append(f"`{m['symbol']}` ▼{abs(m['rank_chg'])} ranks (#{m['pr']}→#{m['cr']})")
                elif abs(m["score_chg"] or 0) >= 1:
                    lines.append(f"`{m['symbol']}` score {m['score_chg']:+.1f}")
            if lines:
                sections.append("**Rank movers** — " + " · ".join(lines))

        # Top opportunities now
        top = c.execute("""SELECT symbol, score, direction FROM score_history
                           WHERE snapshot_ts = (SELECT MAX(snapshot_ts) FROM score_history)
                           ORDER BY score DESC LIMIT 5""").fetchall()
        if top:
            sections.append("**On the radar** — " + ", ".join(
                f"`{r['symbol']}` ({r['score']:.1f} {r['direction']})" for r in top
            ))

        # Today's alerts breakdown
        alerts = c.execute("""SELECT kind, COUNT(*) n FROM alerts
                              WHERE substr(created_at, 1, 10) = ?
                              GROUP BY kind ORDER BY n DESC""", (today,)).fetchall()
        if alerts:
            sections.append("**Alerts fired today** — " + " · ".join(
                f"{a['kind']}×{a['n']}" for a in alerts
            ))
        else:
            sections.append("**Alerts fired today** — none yet.")

        # Imminent earnings (next 7 days)
        earn = c.execute("""SELECT symbol, report_date FROM earnings
                            WHERE report_date BETWEEN date('now') AND date('now', '+7 days')
                            ORDER BY report_date ASC LIMIT 8""").fetchall()
        if earn:
            sections.append("**Earnings this week** — " + ", ".join(
                f"`{e['symbol']}` {e['report_date'][:10]}" for e in earn
            ))

        # Imminent macro events (importance>=2)
        evs = c.execute("""SELECT event_date, title FROM macro_events
                           WHERE event_date BETWEEN date('now') AND date('now', '+5 days')
                             AND importance >= 2
                           ORDER BY event_date ASC LIMIT 5""").fetchall()
        if evs:
            sections.append("**Macro events soon** — " + ", ".join(
                f"{ev['event_date']} {ev['title']}" for ev in evs
            ))

        # Sentiment leaders
        senti = c.execute("""SELECT symbol, ROUND(AVG(sentiment), 2) avg_s, COUNT(*) n
                              FROM news WHERE symbol IS NOT NULL AND sentiment IS NOT NULL
                                AND fetched_at >= datetime('now', '-1 day')
                              GROUP BY symbol HAVING n >= 3
                              ORDER BY ABS(AVG(sentiment)) DESC LIMIT 3""").fetchall()
        if senti:
            sections.append("**Sentiment standouts (24h)** — " + ", ".join(
                f"`{r['symbol']}` {r['avg_s']:+.2f} ({r['n']} articles)" for r in senti
            ))

    if not sections:
        return "_No data yet — refresh from the toolbar._"
    return "\n\n".join(sections)
