"""Daily desk brief — Claude-written end-of-day synthesis, grounded in the DB.

The deterministic layer (scores, signals, radar, digest) finds the numbers;
Claude writes the connective narrative across them. Every fact in the brief
must come from the JSON context block packed here — the system prompt forbids
anything else (DESK_BRIEF_PROMPT.md mirrors it for reference).

One brief per market day, stored in the daily_briefs table (idempotent).
Without ANTHROPIC_API_KEY the feature is a silent no-op and the dashboard
shows the deterministic digest instead.
"""
from __future__ import annotations
import json
import sqlite3
import threading
from datetime import date, datetime, timedelta, timezone
from dk.config import DB_PATH, load_watchlist
from dk import llm
from dk.briefing import radar
from dk.store import db as store

SYSTEM_PROMPT = """You are the analysis layer of DK Investing, a personal market-scanning system. You are not a market-data terminal and you do not monitor anything. Your entire world is the JSON data block provided in the user message: the DK opportunity score with its components, day-over-day rank movers, scored news headlines, alert messages, the Fear & Greed composite, a macro snapshot (VIX, 10Y yield, DXY, WTI, gold, SPX), TradingView technical ratings, earnings and macro calendars, Reddit/StockTwits crowd mentions, off-watchlist market-scan candidates, and broker positions.

Your job is the daily desk brief: connective narrative across precomputed signals. The deterministic layer found the numbers — you explain what is converging, what changed since the prior market day, and what deserves attention next. You surface opportunities to investigate. You never issue instructions to buy or sell.

HARD RULES (these outrank everything below):
1. Every price, level, score, date, or count you state must literally appear in the data block. Describe prices as "last close", never "currently trading at". Open the brief with the block's data_as_of_utc timestamp, and if any row's fetched_at / last_seen / snapshot timestamp is older than that, say so where you cite it.
2. You have NO options data (chains, flow, sweeps, IV, OI, GEX, max pain, greeks), NO dark-pool or block-trade data, NO short-interest or borrow data, NO insider-transaction feed, NO intraday bars (so no VWAP or volume profile), NO Fed-futures probabilities or economic readings, and NO institutional positioning data. If a topic requires any of these, write "no data feed" — that is a correct, high-quality answer.
3. "No signal today" is the preferred body for any section the data block does not support. Never fill a section just to satisfy the template.
4. Never attribute behavior to institutions, smart money, dealers, whales, or market makers. Describe what price and volume did, and which classical interpretation fits.
5. No probabilities, win rates, or confidence percentages. The only 0-100 numbers you may use are the DK opportunity score (quoted verbatim with its stored components: price momentum, volume, news velocity, sentiment, earnings proximity), the market-scan heat score, and the Fear & Greed composite — all attention measures, never probabilities. Never compute a score of your own.
6. Any technical level or rating you cite must come from an input field (e.g. a TradingView RSI value, a rank, a chg_pct). If the block has no field for it, do not cite it.
7. A symbol absent from the data block gets exactly one sentence: "not in the data feed — add it to the watchlist to track it."
8. Source every claim: a score component, an alert message, a rating, or a headline title from the block. Banned unless quoting an input row: "clearly", "massive flow", "smart money is", "institutions are".

OUTPUT FORMAT (markdown, at most ~900 words):
**Data as of:** <data_as_of_utc from the block>

### 1. Market snapshot
The macro tape (VIX / 10Y / DXY / WTI / gold / SPX changes), the Fear & Greed composite — current level and label, its change versus fear_greed_prev if present, and current component levels (note: the breadth component covers only the watchlist, not the whole market) — and macro events within 5 days.

### 2. What changed today
Alerts fired today (quote kinds and messages from alerts_today_detail), and rank changes versus the prior market day from rank_movers (state both snapshot timestamps when citing a move).

### 3. Crowd & flow watch
Reddit/StockTwits mention leaders and StockTwits bull/bear tone, plus any PERSON_ACTIVITY alert rows (tracked public figures). Label all of it explicitly as retail/crowd attention; it is not institutional flow.

### 4. Opportunities lining up
The provided spotlight names: for each, the converging evidence (score + components, reasons, headlines) and what would confirm or invalidate the setup. Before presenting a catalyst headline as the story, check headlines_24h for contradicting coverage on the same name and mention it if found. Include off-watchlist market-scan candidates worth a look.

### 5. On the radar — caution
The provided risk names, with ownership flagged when a broker position exists; earnings within 3 days.

### 6. What to watch next
Earnings in the next 7 days, macro events, event-near alerts. One line each.

Close with one sentence: the single most attention-worthy item and why — framed as "worth investigating", never as a trade instruction.

SELF-CHECK before answering: list internally every section with no supporting rows and write "no signal today" there instead of content. Then verify no sentence states a number, price, or date that is absent from the data block."""

# One generation at a time per process; backoff after a failed attempt so a
# persistent API problem doesn't retry on every 15-minute poll.
_gen_lock = threading.Lock()
_last_failed_attempt: datetime | None = None


def _cfg() -> dict:
    return (load_watchlist().get("brief") or {})


def _utc_today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def build_context() -> dict:
    """Pack everything the brief may cite into one JSON-serializable dict.
    Pure DB reads — no network calls, safe to run any time."""
    ctx: dict = {
        "context_built_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }

    with sqlite3.connect(DB_PATH) as c:
        c.row_factory = sqlite3.Row

        ctx["macro_tape"] = [dict(r) for r in c.execute(
            "SELECT symbol, label, last_value, chg_pct, fetched_at FROM macro_context")]

        fg_rows = c.execute(
            """SELECT snapshot_ts, composite, label, components_json
               FROM market_sentiment ORDER BY snapshot_ts DESC LIMIT 2""").fetchall()
        if fg_rows:
            try:
                components = json.loads(fg_rows[0]["components_json"] or "{}")
            except Exception:
                components = {}
            ctx["fear_greed"] = {"snapshot_ts": fg_rows[0]["snapshot_ts"],
                                 "composite": fg_rows[0]["composite"],
                                 "label": fg_rows[0]["label"],
                                 "components": components}
            if len(fg_rows) > 1:
                ctx["fear_greed_prev"] = {"snapshot_ts": fg_rows[1]["snapshot_ts"],
                                          "composite": fg_rows[1]["composite"],
                                          "label": fg_rows[1]["label"]}

        latest_ts = c.execute("SELECT MAX(snapshot_ts) FROM score_history").fetchone()[0]
        if latest_ts:
            ctx["opportunity_scores"] = [dict(r) for r in c.execute(
                """SELECT symbol, rank, score, direction, price_mom, vol_mom,
                          news_vel, sentiment, earn_prox, headline_count_24h
                   FROM score_history WHERE snapshot_ts=? ORDER BY rank""",
                (latest_ts,))]
            ctx["scores_snapshot_ts"] = latest_ts

        # Day-over-day movers: latest snapshot vs the last snapshot of a PRIOR
        # day (snapshots are written every poll cycle, so the immediately
        # preceding one is only minutes old and would show no real movement).
        ctx["rank_movers"] = [dict(r) for r in c.execute("""
            SELECT cur.symbol, cur.snapshot_ts cur_ts, prv.snapshot_ts prev_ts,
                   cur.rank cur_rank, cur.score cur_score,
                   prv.rank prev_rank, prv.score prev_score,
                   (prv.rank - cur.rank) AS rank_chg
            FROM score_history cur
            JOIN score_history prv ON prv.symbol = cur.symbol
            WHERE cur.snapshot_ts = (SELECT MAX(snapshot_ts) FROM score_history)
              AND prv.snapshot_ts = (
                  SELECT MAX(snapshot_ts) FROM score_history
                   WHERE substr(snapshot_ts, 1, 10) <
                         substr((SELECT MAX(snapshot_ts) FROM score_history), 1, 10))
            ORDER BY ABS(rank_chg) DESC LIMIT 5""")]

        ctx["headlines_24h"] = [dict(r) for r in c.execute(
            """SELECT symbol, source, title, url, sentiment, is_breaking, published
               FROM news WHERE fetched_at >= datetime('now', '-1 day')
                 AND sentiment IS NOT NULL
               ORDER BY is_breaking DESC, ABS(sentiment) DESC LIMIT 15""")]

        utc_today = _utc_today()
        ctx["alerts_today_counts"] = [dict(r) for r in c.execute(
            """SELECT kind, COUNT(*) n FROM alerts
               WHERE substr(created_at, 1, 10) = ? AND kind != 'SETUP_TRACK'
               GROUP BY kind ORDER BY n DESC""", (utc_today,))]
        ctx["alerts_today_detail"] = [dict(r) for r in c.execute(
            """SELECT kind, symbol, message, created_at FROM alerts
               WHERE substr(created_at, 1, 10) = ? AND kind != 'SETUP_TRACK'
               ORDER BY created_at DESC LIMIT 30""", (utc_today,))]

        ctx["trending"] = [dict(r) for r in c.execute(
            """SELECT symbol, source, mention_count, sentiment, fetched_at
               FROM trending_mentions
               WHERE fetched_at >= datetime('now', '-1 day')
               ORDER BY mention_count DESC LIMIT 15""")]

        ctx["tradingview_ratings"] = [dict(r) for r in c.execute(
            """SELECT symbol, interval, recommendation, buy_signals, sell_signals,
                      neutral_signals, rsi, fetched_at
               FROM tv_ratings WHERE fetched_at >= datetime('now', '-2 days')
               ORDER BY symbol, interval""")]

        ctx["market_scan_candidates"] = [dict(r) for r in c.execute(
            """SELECT symbol, name, last_price, score, score_direction, notes, last_seen
               FROM candidates WHERE discovered_via='market_scan'
                 AND last_seen >= datetime('now', '-1 day')
               ORDER BY score DESC LIMIT 10""")]

        ctx["earnings_next_7d"] = [dict(r) for r in c.execute(
            """SELECT symbol, report_date, eps_estimate FROM earnings
               WHERE report_date BETWEEN date('now') AND date('now', '+7 days')
               ORDER BY report_date LIMIT 10""")]

        ctx["macro_events_next_5d"] = [dict(r) for r in c.execute(
            """SELECT event_date, title, category, importance FROM macro_events
               WHERE event_date BETWEEN date('now') AND date('now', '+5 days')
                 AND importance >= 2 ORDER BY event_date LIMIT 8""")]

        # quantity != 0 so short positions count as ownership too
        ctx["positions"] = [dict(r) for r in c.execute(
            """SELECT broker, symbol, quantity, market_value FROM positions
               WHERE quantity != 0 ORDER BY ABS(market_value) DESC""")]

    # Radar syntheses. Internal conviction/risk/priority numbers are stripped —
    # hard rule 5 limits which 0-100 numbers the model may quote.
    ctx["spotlight"] = [
        {k: s.get(k) for k in ("symbol", "score", "direction", "rank", "reasons",
                               "owned", "catalyst_headline", "catalyst_url")}
        for s in radar.opportunity_spotlight(limit=5)
    ]
    ctx["risks"] = [
        {k: r.get(k) for k in ("symbol", "reasons", "owned")}
        for r in radar.watchlist_risks(limit=4)
    ]
    ctx["radar_cards"] = [
        {k: card.get(k) for k in ("category", "symbol", "headline", "kind",
                                  "owned", "url", "ts")}
        for card in radar.build_radar(hours=24, limit=15)
    ]

    # The freshest data timestamp — what the brief should present as "as of".
    candidates = [ctx.get("scores_snapshot_ts")]
    candidates += [m.get("fetched_at") for m in ctx["macro_tape"]]
    if ctx.get("fear_greed"):
        candidates.append(ctx["fear_greed"].get("snapshot_ts"))
    freshest = max((t for t in candidates if t), default=None)
    ctx["data_as_of_utc"] = freshest or ctx["context_built_at_utc"]
    return ctx


def get(brief_date: str) -> dict | None:
    with store.conn() as c:  # store.conn() runs init_db, so the table always exists
        row = c.execute(
            """SELECT brief_date, generated_at, model, input_tokens, output_tokens, markdown
               FROM daily_briefs WHERE brief_date=?""", (brief_date,)).fetchone()
        return dict(row) if row else None


def latest() -> dict | None:
    with store.conn() as c:
        row = c.execute(
            """SELECT brief_date, generated_at, model, input_tokens, output_tokens, markdown
               FROM daily_briefs ORDER BY brief_date DESC LIMIT 1""").fetchone()
        return dict(row) if row else None


def generate(force: bool = False, brief_date: str | None = None) -> dict:
    """Generate (or return the cached) brief for brief_date (default: today UTC).
    Stores only real LLM output, so adding a key later still produces a brief."""
    global _last_failed_attempt
    store.init_db()
    brief_date = brief_date or _utc_today()

    with _gen_lock:
        if not force:
            existing = get(brief_date)
            if existing:
                return {**existing, "cached": True, "llm": True}

        ctx = build_context()
        if not ctx.get("opportunity_scores") and not ctx.get("macro_tape"):
            return {"llm": False, "note": "No data in the DB yet — run a refresh first."}

        cfg = _cfg()
        model = cfg.get("model") or llm.DEFAULT_MODEL
        prompt = ("Today's data block (JSON). Write the desk brief from it and "
                  "nothing else.\n\n```json\n"
                  + json.dumps(ctx, sort_keys=True, default=str)
                  + "\n```")
        result = llm.complete(prompt, system=SYSTEM_PROMPT, model=model,
                              max_tokens=12000,
                              adaptive_thinking=llm.supports_adaptive_thinking(model))
        if result is None:
            return {"llm": False,
                    "note": "Claude unavailable — set ANTHROPIC_API_KEY in "
                            "config/secrets.env and run `uv sync` "
                            "(the deterministic digest still works)."}
        if result.get("error"):
            _last_failed_attempt = datetime.now(timezone.utc)
            return {"llm": False, "note": f"Claude call failed: {result['error']}"}

        text = result["text"]
        if result.get("stop_reason") == "max_tokens":
            text += "\n\n*[Brief hit the output limit and may be truncated.]*"

        with store.conn() as c:
            c.execute(
                """INSERT OR REPLACE INTO daily_briefs
                   (brief_date, generated_at, model, input_tokens, output_tokens,
                    markdown, context_json)
                   VALUES (?, CURRENT_TIMESTAMP, ?, ?, ?, ?, ?)""",
                (brief_date, result["model"], result["input_tokens"],
                 result["output_tokens"], text,
                 json.dumps(ctx, sort_keys=True, default=str)))

    out = {**get(brief_date), "cached": False, "llm": True}

    if cfg.get("send_to_phone"):
        try:
            from dk.notify import sms
            sms.send_brief(text)
        except Exception as e:
            print(f"[desk_brief] phone push failed: {e}")
    return out


def _target_brief_date(now: datetime, hour: int) -> date:
    """The most recent weekday whose close-hour has already passed."""
    target = (now - timedelta(hours=hour)).date()
    while target.weekday() >= 5:  # roll Sat/Sun back to Friday
        target -= timedelta(days=1)
    return target


def maybe_generate() -> dict:
    """Poller gate. Generates the brief for the most recent market day whose
    close has passed, if it doesn't exist yet and we're within 12h of that
    close (daily bars still describe that session). Cheap no-op otherwise."""
    cfg = _cfg()
    if not cfg.get("enabled", True):
        return {"skipped": "disabled"}
    if not llm.is_available():
        return {"skipped": "no ANTHROPIC_API_KEY (or anthropic package missing)"}
    now = datetime.now(timezone.utc)
    if _last_failed_attempt and (now - _last_failed_attempt) < timedelta(minutes=60):
        return {"skipped": "retry backoff — last attempt failed under an hour ago"}
    hour = int(cfg.get("hour_utc", 21))
    target = _target_brief_date(now, hour)
    target_close = datetime(target.year, target.month, target.day, hour,
                            tzinfo=timezone.utc)
    if now - target_close > timedelta(hours=12):
        return {"skipped": f"missed the window for {target} (use the dashboard button)"}
    if get(target.isoformat()):
        return {"skipped": f"brief for {target} already exists"}
    res = generate(brief_date=target.isoformat())
    if res.get("llm"):
        return {"generated": True, "brief_date": target.isoformat(),
                "model": res.get("model"), "output_tokens": res.get("output_tokens")}
    return {"skipped": res.get("note", "llm unavailable")}
