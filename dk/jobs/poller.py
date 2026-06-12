"""Run a full data refresh cycle. Invoke directly:
    uv run python -m dk.jobs.poller
"""
from __future__ import annotations
import time
from dk.config import equity_symbols, crypto_ids, load_watchlist
from dk.store import db as store
from dk.sources import (
    prices_yfinance,
    news_rss,
    news_newsapi,
    earnings_finnhub,
    crypto_coingecko,
    macro_calendar,
    ipos_finnhub,
)
from dk.sentiment import scorer as sentiment_scorer
from dk.jobs import alerts as alert_engine
from dk.notify import discord as discord_notifier


def run_once() -> dict:
    """Public entry: wraps the poll with status tracking so the UI can show a
    live loading indicator and detect completion."""
    store.init_db()
    store.set_poll_running()
    summary: dict = {}
    try:
        summary = _run_once_impl()
        return summary
    finally:
        store.set_poll_done(summary)


def _run_once_impl() -> dict:
    store.init_db()
    summary: dict[str, int] = {}
    syms = equity_symbols()
    wl = load_watchlist()
    name_lookup = {e["symbol"]: e.get("name", e["symbol"]) for e in (wl.get("equities") or []) + (wl.get("etfs") or [])}

    print(f"[poller] {len(syms)} equities/ETFs: {syms}")

    # Prices
    p_total = 0
    for s in syms:
        n = prices_yfinance.fetch_prices(s)
        p_total += n
        time.sleep(0.2)
    summary["prices_rows"] = p_total

    # Earnings via yfinance (free)
    e_total = 0
    for s in syms:
        e_total += prices_yfinance.fetch_earnings(s)
        time.sleep(0.1)
    summary["earnings_yf"] = e_total

    # Earnings calendar via Finnhub (if key set)
    summary["earnings_finnhub"] = earnings_finnhub.fetch_calendar(days_ahead=30)

    # Global news (now 23 free RSS feeds incl. wires + Fed + SEC + Treasury)
    summary["news_global"] = news_rss.fetch_global()

    # Crypto-specific news (CoinDesk, The Block, Decrypt, CoinTelegraph)
    summary["news_crypto"] = news_rss.fetch_crypto()

    # Per-ticker news (Yahoo RSS — free)
    summary["news_per_ticker"] = news_rss.fetch_per_ticker(syms)

    # NewsAPI per ticker (if key set)
    napi_total = 0
    for s in syms:
        napi_total += news_newsapi.fetch_for_symbol(s, name_lookup.get(s))
        time.sleep(0.5)
    summary["news_newsapi"] = napi_total

    # Crypto
    summary["crypto_rows"] = crypto_coingecko.fetch_prices(crypto_ids())

    # Macro + IPO calendars
    summary["macro_events"] = macro_calendar.load()
    summary["ipos"] = ipos_finnhub.fetch_all()

    # Macro context (VIX, DXY, yields, oil, gold, SPX)
    from dk.sources import macro_context as mctx
    try:
        summary["macro_context"] = mctx.fetch_all()
    except Exception as e:
        print(f"[macro_context] {e}")
        summary["macro_context"] = 0

    # Curated events calendar (Jensen GTC, Powell speeches, OPEC, etc.)
    from dk.sources import events_calendar
    try:
        summary["events_alerts"] = events_calendar.check_and_alert()
    except Exception as e:
        print(f"[events_calendar] {e}")
        summary["events_alerts"] = 0

    # Power players tracking (Trump, Musk, Powell, Buffett, every CEO who moves stocks)
    from dk.sources import people_tracker
    try:
        summary["person_alerts"] = people_tracker.detect_and_alert(window_hours=4)
    except Exception as e:
        print(f"[people_tracker] {e}")
        summary["person_alerts"] = 0

    # X (Twitter) posts via Nitter/RSSHub for tracked power players
    from dk.sources import x_feeds
    try:
        summary["x_posts"] = x_feeds.fetch_all()
    except Exception as e:
        print(f"[x_feeds] {e}")
        summary["x_posts"] = 0

    # TradingView technical ratings (free; no account needed)
    from dk.sources import tradingview_ratings
    try:
        summary["tv_ratings"] = tradingview_ratings.fetch_for_watchlist(intervals=["1d"])
    except Exception as e:
        print(f"[tv-ratings] {e}")
        summary["tv_ratings"] = 0

    # Discovery scanner — find new candidates from news mentions
    from dk.discovery import scanner as discovery
    try:
        disc = discovery.scan(min_mentions=3, max_validate=20)
        summary["discovery"] = disc
    except Exception as e:
        print(f"[discovery] {e}")
        summary["discovery"] = {"error": str(e)}

    # Market-wide scan — gainers/losers/most-active across the WHOLE market,
    # heat-scored with our news + reddit data (no per-ticker fetches).
    from dk.discovery import market_scan
    try:
        summary["market_scan"] = market_scan.scan()
    except Exception as e:
        print(f"[market_scan] {e}")
        summary["market_scan"] = {"error": str(e)}

    # Multi-source trending: Reddit + StockTwits
    from dk.sources import trending_reddit, trending_stocktwits
    try:
        summary["trending_reddit"] = trending_reddit.fetch()
    except Exception as e:
        print(f"[trending_reddit] {e}")
        summary["trending_reddit"] = 0
    try:
        summary["trending_stocktwits"] = trending_stocktwits.fetch()
    except Exception as e:
        print(f"[trending_stocktwits] {e}")
        summary["trending_stocktwits"] = 0

    # Theme scoring (no on-demand fetch in poll cycle to keep it fast)
    from dk.themes import registry as themes_reg
    try:
        scored = themes_reg.score_all(fetch_missing=False)
        summary["themes_scored"] = len(scored)
    except Exception as e:
        print(f"[themes] {e}")
        summary["themes_scored"] = 0

    # Broker portfolio sync (graceful skip if no creds)
    from dk.brokers import sync as broker_sync
    try:
        summary["brokers"] = broker_sync.sync_all()
    except Exception as e:
        print(f"[brokers] {e}")
        summary["brokers"] = {"error": str(e)}

    # Sentiment scoring (only unscored rows)
    summary["sentiment_scored"] = sentiment_scorer.score_unscored()

    # Market-wide sentiment composite
    from dk.sentiment import market as market_sent
    try:
        snap = market_sent.persist_snapshot()
        summary["market_sentiment"] = snap.get("composite")
    except Exception as e:
        print(f"[market_sentiment] {e}")
        summary["market_sentiment"] = None

    # Opportunity score snapshot + rank/score delta alerts
    from dk.opportunity import delta as opp_delta
    delta_summary = opp_delta.snapshot_and_alert()
    summary["score_snapshot"] = delta_summary.get("snapshotted", 0)
    summary["delta_alerts"] = delta_summary.get("new_alerts", 0)
    if delta_summary.get("discoveries"):
        print("[discoveries]")
        for d in delta_summary["discoveries"]:
            try:
                print(f"  - {d}")
            except UnicodeEncodeError:
                print(f"  - {d.encode('ascii', 'replace').decode()}")

    # Alert engine (price/volume/earnings/sentiment/macro/crypto)
    alerts_summary = alert_engine.run()
    summary["alerts_new"] = alerts_summary.get("total_new", 0)
    summary["alerts_breakdown"] = alerts_summary

    # Custom user-defined alerts
    from dk.jobs import custom_alerts as ca
    try:
        summary["custom_alerts_fired"] = ca.evaluate()
    except Exception as e:
        print(f"[custom_alerts] {e}")
        summary["custom_alerts_fired"] = 0

    # Push to Discord if webhook configured (no-op otherwise)
    summary["discord_pushed"] = discord_notifier.push_unsent()

    # Push live-event digest SMS to phone (no-op unless configured)
    from dk.notify import sms as sms_notifier
    try:
        summary["sms"] = sms_notifier.push_digest()
    except Exception as e:
        print(f"[sms] {e}")
        summary["sms"] = {"error": str(e)}

    # Daily desk brief — Claude-written synthesis, once per market day after
    # the configured UTC hour (no-op without ANTHROPIC_API_KEY)
    try:
        from dk.briefing import desk_brief
        summary["desk_brief"] = desk_brief.maybe_generate()
    except Exception as e:
        print(f"[desk_brief] {e}")
        summary["desk_brief"] = {"error": str(e)}

    print(f"[poller] done: {summary}")
    return summary


if __name__ == "__main__":
    run_once()
