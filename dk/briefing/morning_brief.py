"""Pre-open morning brief — Claude-written, the AM counterpart to the desk brief.

Reuses desk_brief.build_context() (pure DB reads) and layers on LIVE pre-open
data: US index futures + overseas indices (overnight_markets) and pre-market
gappers (premarket). Same hard anti-fabrication rules as the desk brief — every
number must appear in the JSON block. Generated once per trading day, ~08:30 ET
(before the open), stored in morning_briefs (idempotent), pushed to Telegram.
Silent no-op without ANTHROPIC_API_KEY.
"""
from __future__ import annotations
import json
import sqlite3
import threading
from datetime import date, datetime, timedelta, timezone
from dk.config import DB_PATH, load_watchlist
from dk import llm
from dk.briefing import desk_brief
from dk.sources import overnight_markets, premarket, market_movers
from dk.store import db as store

SYSTEM_PROMPT = """You are the analysis layer of DK Investing, writing the PRE-OPEN morning brief. You are not a market terminal and you monitor nothing. Your entire world is the JSON data block in the user message: US index futures and overseas index moves (overnight_markets), pre-market gappers (premarket_gappers, with prior-close and pre-market price), the DK opportunity scores, scored headlines (incl. overnight), alerts, Fear & Greed, a macro snapshot, TradingView ratings, today's and the week's earnings, macro calendar, crowd mentions, off-watchlist scan candidates, and broker positions.

Your job: a tight pre-open read of what moved overnight and what is set up into the US open. The deterministic layer found the numbers; you connect them. You surface things to investigate. You NEVER issue buy/sell instructions.

HARD RULES (these outrank everything):
1. Every price, level, %, date, or count you state must literally appear in the data block. Pre-market and futures levels: cite them as "pre-market" / "futures", with the prior close they move from. Open with data_as_of_utc.
2. You have NO options/flow/IV/OI data, NO dark-pool or short-interest data, NO insider feed, NO intraday RTH bars, NO Fed-futures probabilities, NO institutional positioning. If a topic needs any of these, write "no data feed".
3. "No signal" is the right body for any unsupported section. Never pad.
4. Never attribute action to institutions/smart money/dealers/whales/market makers. Describe what price did and the classical interpretation.
5. No probabilities or confidence %. The only 0-100 numbers allowed are the DK opportunity score (with its stored components), the market-scan heat, and the Fear & Greed composite — all attention measures.
6. Pre-market moves are thin and can reverse at the open — say so. A futures move is direction, not a guarantee.
7. A symbol absent from the block gets one sentence: "not in the data feed — add it to the watchlist to track it."
8. Source every claim to an input row (a gap %, a futures chg_pct, a headline title, a score component).

OUTPUT FORMAT (markdown, at most ~700 words):
**Pre-open brief — data as of:** <data_as_of_utc>

### 1. Overnight tape
US futures (ES/NQ/YM/RTY chg_pct from overnight_markets.futures) and the overseas session (overnight_markets.overseas: Nikkei/Hang Seng/DAX/FTSE). One or two sentences on risk-on vs risk-off direction into the open. If a field is missing, say so.

### 2. Pre-market movers
From premarket_gappers: the notable gappers, watchlist names first (on_watchlist=true), each with its gap_pct and pre-market vs prior_close. Flag that pre-market liquidity is thin. "No pre-market gappers in the feed" if empty.

### 3. Today's catalysts
earnings_today (reporting before the open / today) and macro events today/near from macro_events_next_5d. One line each. Note which watchlist names report.

### 4. Setups into the open
The spotlight names: converging evidence (score + components, reasons, headlines) and what a pre-market gap or overnight headline confirms or contradicts. Cross-check headlines_24h for contradicting coverage.

### 5. Watch at the open
The single most attention-worthy item into the open and why — "worth investigating", never a trade instruction.

SELF-CHECK before answering: for each section with no supporting rows, write "no signal" instead of inventing content; verify no number/price/date is absent from the block."""

_gen_lock = threading.Lock()
_last_failed_attempt: datetime | None = None


def _cfg() -> dict:
    return (load_watchlist().get("morning_brief") or {})


def _utc_today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _watchlist_symbols() -> list[str]:
    wl = load_watchlist()
    syms: list[str] = []
    for grp in ("equities", "etfs"):
        for item in (wl.get(grp) or []):
            s = item.get("symbol") if isinstance(item, dict) else item
            if s:
                syms.append(s)
    return syms


def _augment_context(ctx: dict) -> dict:
    """Add live pre-open data to the desk-brief context."""
    try:
        ctx["overnight_markets"] = overnight_markets.fetch()
    except Exception as e:
        ctx["overnight_markets"] = {"error": str(e)}
    try:
        movers = []
        try:
            movers = [m["symbol"] for m in market_movers.fetch_movers() if m.get("symbol")]
        except Exception:
            pass
        gappers, health = premarket.scan_gaps(
            _watchlist_symbols(), movers,
            watchlist_min_pct=1.5, movers_min_pct=4.0, max_movers=30)
        ctx["premarket_gappers"] = gappers  # always a list (documented shape)
        ctx["premarket_status"] = "feed unavailable" if health.get("degraded") else "ok"
    except Exception as e:
        ctx["premarket_gappers"] = []
        ctx["premarket_status"] = f"error: {e}"
    try:
        with sqlite3.connect(DB_PATH) as c:
            c.row_factory = sqlite3.Row
            ctx["earnings_today"] = [dict(r) for r in c.execute(
                """SELECT symbol, report_date, eps_estimate FROM earnings
                   WHERE report_date = date('now') ORDER BY symbol""")]
    except Exception as e:
        ctx["earnings_today"] = []
        ctx["earnings_today_error"] = str(e)
    return ctx


def get(brief_date: str) -> dict | None:
    with store.conn() as c:
        row = c.execute(
            """SELECT brief_date, generated_at, model, input_tokens, output_tokens, markdown
               FROM morning_briefs WHERE brief_date=?""", (brief_date,)).fetchone()
        return dict(row) if row else None


def latest() -> dict | None:
    with store.conn() as c:
        row = c.execute(
            """SELECT brief_date, generated_at, model, input_tokens, output_tokens, markdown
               FROM morning_briefs ORDER BY brief_date DESC LIMIT 1""").fetchone()
        return dict(row) if row else None


def generate(force: bool = False, brief_date: str | None = None) -> dict:
    global _last_failed_attempt
    store.init_db()
    brief_date = brief_date or _utc_today()
    with _gen_lock:
        if not force:
            existing = get(brief_date)
            if existing:
                return {**existing, "cached": True, "llm": True}

        ctx = desk_brief.build_context()
        ctx = _augment_context(ctx)
        # overnight_markets.fetch() ALWAYS returns a dict ({} or {"error":...}), so
        # it's truthy regardless — check for actual rows, not just presence.
        om = ctx.get("overnight_markets")
        have_markets = isinstance(om, dict) and (om.get("futures") or om.get("overseas"))
        if not ctx.get("opportunity_scores") and not ctx.get("macro_tape") \
                and not have_markets:
            return {"llm": False, "note": "No data yet — run a refresh first."}

        cfg = _cfg()
        model = cfg.get("model") or llm.DEFAULT_MODEL
        prompt = ("Pre-open data block (JSON). Write the morning brief from it and "
                  "nothing else.\n\n```json\n"
                  + json.dumps(ctx, sort_keys=True, default=str)
                  + "\n```")
        result = llm.complete(prompt, system=SYSTEM_PROMPT, model=model,
                              max_tokens=9000,
                              adaptive_thinking=llm.supports_adaptive_thinking(model))
        if result is None:
            return {"llm": False, "note": "Claude unavailable — set ANTHROPIC_API_KEY."}
        if result.get("error"):
            _last_failed_attempt = datetime.now(timezone.utc)
            return {"llm": False, "note": f"Claude call failed: {result['error']}"}

        text = result["text"]
        if result.get("stop_reason") == "max_tokens":
            text += "\n\n*[Brief hit the output limit and may be truncated.]*"

        with store.conn() as c:
            c.execute(
                """INSERT OR REPLACE INTO morning_briefs
                   (brief_date, generated_at, model, input_tokens, output_tokens,
                    markdown, context_json)
                   VALUES (?, CURRENT_TIMESTAMP, ?, ?, ?, ?, ?)""",
                (brief_date, result["model"], result["input_tokens"],
                 result["output_tokens"], text,
                 json.dumps(ctx, sort_keys=True, default=str)))

    out = {**get(brief_date), "cached": False, "llm": True}
    if cfg.get("send_to_phone", True):
        try:
            from dk.notify import sms
            sms.send_brief(text)
        except Exception as e:
            print(f"[morning_brief] phone push failed: {e}")
    return out


def maybe_generate() -> dict:
    """Poller gate: generate once on a trading-day morning, within the pre-open
    window (between morning_hour_utc and ~2h later), if not already done."""
    from dk.util import session
    cfg = _cfg()
    if not cfg.get("enabled", True):
        return {"skipped": "disabled"}
    if not llm.is_available():
        return {"skipped": "no ANTHROPIC_API_KEY"}
    if not session.is_trading_day():
        return {"skipped": "not a trading day"}
    global _last_failed_attempt
    if _last_failed_attempt and (datetime.now(timezone.utc) - _last_failed_attempt) < timedelta(minutes=60):
        return {"skipped": "retry backoff"}
    # ET-anchored pre-open window (DST-correct via the session clock, no fixed-UTC
    # drift). hour_et default 8 (08:30 ET); a wide window self-heals missed polls.
    et = session.now_et()
    start = et.replace(hour=int(cfg.get("hour_et", 8)),
                       minute=int(cfg.get("minute", 30)), second=0, microsecond=0)
    if et < start:
        return {"skipped": f"before the {start:%H:%M} ET pre-open window"}
    if et - start > timedelta(hours=float(cfg.get("window_hours", 2.5))):
        return {"skipped": "past the pre-open window for today"}
    today = _utc_today()
    if get(today):
        return {"skipped": f"morning brief for {today} already exists"}
    res = generate(brief_date=today)
    if res.get("llm"):
        return {"generated": True, "brief_date": today,
                "model": res.get("model"), "output_tokens": res.get("output_tokens")}
    return {"skipped": res.get("note", "llm unavailable")}
