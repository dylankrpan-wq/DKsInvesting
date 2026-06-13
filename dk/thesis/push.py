"""Event-triggered stock thesis pushes to Telegram.

When a watchlist or discovered name forms a setup (bullish/bearish convergence
from the radar, or a high-heat market-scan candidate), generate a concise
forward-looking thesis note — what may happen and why, from chart behavior +
sentiment/momentum + catalyst — and push it to the phone. Per-name cooldown so
the same stock isn't pushed repeatedly; per-cycle cap so a busy tape doesn't
burst. Runs inside the poll cycle (so it needs the scheduler up).

Grounded: the note is built from the thesis generator's MEASURED data
(opportunity score + components, technicals, news sentiment, earnings). Framed
as an idea to investigate with an invalidation level — never a buy/sell call.
"""
from __future__ import annotations
import json
import sqlite3
from dk.config import DB_PATH, load_watchlist, equity_symbols
from dk import llm
from dk.briefing import radar


def _cfg() -> dict:
    return (load_watchlist().get("thesis_push") or {})


# A convergence name only becomes a "forming setup" worth a thesis when
# something fresh fired today — otherwise it's just a standing high score.
_TRIGGER_KINDS = ("TECH_SIGNAL", "RANK_JUMP", "NEW_TOP", "SCORE_SURGE",
                  "EARNINGS_NEAR", "HIGH_IMPACT_NEWS", "NEWS_VELOCITY")


def _has_fresh_trigger(c, symbol: str, hours: int) -> bool:
    ph = ",".join("?" * len(_TRIGGER_KINDS))
    return c.execute(
        f"""SELECT 1 FROM alerts WHERE symbol=? AND kind IN ({ph})
            AND created_at >= datetime('now', ?) LIMIT 1""",
        (symbol, *_TRIGGER_KINDS, f"-{hours} hours")).fetchone() is not None


def _candidates() -> list[dict]:
    """(symbol, direction, reason) for names with a setup forming, deduped.
    Convergence names require a fresh trigger today (event-triggered); discovered
    market-scan movers are inherently fresh (today's mover + signal)."""
    cfg = _cfg()
    fresh_h = int(cfg.get("fresh_trigger_hours", 8))
    seen: dict[str, dict] = {}

    with sqlite3.connect(DB_PATH) as c:
        c.row_factory = sqlite3.Row

        for s in radar.opportunity_spotlight(limit=8):
            sym = s["symbol"].upper()
            if sym not in seen and _has_fresh_trigger(c, sym, fresh_h):
                seen[sym] = {"symbol": sym, "direction": "bull",
                             "reason": "bullish convergence: " + ", ".join(s.get("reasons", [])),
                             "source": "spotlight"}
        for r in radar.watchlist_risks(limit=8):
            sym = r["symbol"].upper()
            if sym not in seen and _has_fresh_trigger(c, sym, fresh_h):
                seen[sym] = {"symbol": sym, "direction": "bear",
                             "reason": "bearish convergence: " + ", ".join(r.get("reasons", [])),
                             "source": "risk"}

        if cfg.get("include_discovered", True):
            heat_min = float(cfg.get("scan_heat_min", 40))
            rows = c.execute(
                """SELECT symbol, score, score_direction, notes FROM candidates
                   WHERE discovered_via='market_scan'
                     AND last_seen >= datetime('now','-1 day')
                     AND score >= ? AND score_direction IN ('bull','bear')
                   ORDER BY score DESC LIMIT 8""", (heat_min,)).fetchall()
            for r in rows:
                sym = (r["symbol"] or "").upper()
                if sym and sym not in seen:
                    seen[sym] = {"symbol": sym, "direction": r["score_direction"],
                                 "reason": f"market scan (heat {r['score']:.0f}): {r['notes'] or ''}",
                                 "source": "discovered"}
    return list(seen.values())


def _in_cooldown(c, symbol: str, hours: int) -> bool:
    return c.execute(
        """SELECT 1 FROM alerts WHERE symbol=? AND kind='THESIS'
           AND created_at >= datetime('now', ?) LIMIT 1""",
        (symbol, f"-{hours} hours")).fetchone() is not None


_SYSTEM = """You write a SHORT forward-looking thesis note on one stock for an experienced trader, to be read on a phone. You are given the name's MEASURED data: opportunity score + components, technical indicators, news sentiment/momentum, recent catalyst headline, and earnings proximity.

Rules:
- Use ONLY values present in the data. Never invent a price, level, or figure.
- 3-4 sentences. Cover: (1) what the chart/momentum is doing, (2) the company/news angle if present, (3) what may happen next and the level or event that would confirm or invalidate it.
- Forward-looking and specific, but framed as an idea to investigate — never "buy"/"sell".
- No hype, no emoji, no preamble. Just the note."""


def _note(symbol: str, direction: str, reason: str) -> str:
    """Concise Claude thesis note grounded in the thesis data; template fallback."""
    from dk.thesis import generator as thesis_gen
    try:
        th = thesis_gen.build(symbol)
    except Exception as e:
        print(f"[thesis_push] build {symbol} failed: {e}")
        return ""
    data = {
        "symbol": symbol, "company": th.company, "sector": th.sector,
        "direction": direction, "trigger": reason,
        "opportunity_score": round(th.score, 1), "score_direction": th.direction,
        "technicals": th.technicals, "sentiment": th.sentiment,
        "earnings": th.earnings,
        "top_catalyst": th.catalysts[0] if th.catalysts else None,
        "risks": th.risks,
    }
    prompt = ("Write the thesis note from this data:\n\n```json\n"
              + json.dumps(data, sort_keys=True, default=str) + "\n```")
    res = llm.complete(prompt, system=_SYSTEM, model=_cfg().get("model") or llm.DEFAULT_MODEL,
                       max_tokens=600, adaptive_thinking=True)
    if res and res.get("text"):
        return res["text"].strip()
    # deterministic fallback
    t = th.technicals or {}
    bits = [f"{symbol} ({th.company}) — {direction} setup forming (DK score {th.score:.0f})."]
    if t.get("trend"):
        bits.append(f"Trend {t['trend']}, RSI {t.get('rsi14','?')}.")
    if th.catalysts:
        bits.append(f"Catalyst: {th.catalysts[0]['title'][:120]}.")
    if th.earnings.get("days_out") is not None:
        bits.append(f"Earnings in {th.earnings['days_out']}d.")
    return " ".join(bits)


def push_theses(push: bool = True) -> dict:
    """Generate + push thesis notes for fresh setups. No-op without phone/config."""
    cfg = _cfg()
    if not cfg.get("enabled", True):
        return {"skipped": "disabled"}
    from dk.notify import sms
    if not sms.is_configured():
        return {"skipped": "no phone channel"}

    cap = int(cfg.get("max_per_cycle", 2))
    cooldown = int(cfg.get("cooldown_hours", 12))
    cands = _candidates()
    if not cands:
        return {"candidates": 0, "pushed": 0}

    sent_notes: list[str] = []
    pushed = 0
    from dk.store import db as store
    store.init_db()
    with store.conn() as c:
        for cand in cands:
            if pushed >= cap:
                break
            sym = cand["symbol"]
            if _in_cooldown(c, sym, cooldown):
                continue
            note = _note(sym, cand["direction"], cand["reason"])
            if not note:
                continue
            arrow = "🟢" if cand["direction"] == "bull" else "🔴"
            headline = f"📋 Thesis: {arrow} {sym} ({cand['direction']})"
            c.execute(
                "INSERT INTO alerts (symbol, kind, message, payload) VALUES (?,?,?,?)",
                (sym, "THESIS", headline,
                 json.dumps({"direction": cand["direction"], "source": cand["source"],
                             "reason": cand["reason"], "note": note})))
            sent_notes.append(f"{headline}\n{note}")
            pushed += 1

    summary = {"candidates": len(cands), "pushed": pushed}
    if push and sent_notes:
        body = "📋 Stock theses — potential setups forming:\n\n" + "\n\n".join(sent_notes)
        try:
            summary["chunks"] = sms.send_summary(body)
        except Exception as e:
            print(f"[thesis_push] send failed: {e}")
            summary["error"] = str(e)
    return summary


if __name__ == "__main__":
    import io
    import sys
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    print(push_theses(push=False))
