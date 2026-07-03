"""Market Highlights push -> phone/group.

A broad market snapshot (vs. the sector-focused digest): the day's biggest
movers, the most-active/popular stocks and ETFs, ETF moves, and real-world
highlights (macro events + major market-wide news/deals). Runs on its own
interval, market-hours gated, de-duplicated on the news it has already sent.
"""
from __future__ import annotations
import sqlite3
from dk.config import DB_PATH, load_watchlist
from dk.sources import market_movers, leaderboards
from dk.notify import sms as _sms
from dk.util import links as _lk

# Popular ETFs to always show a read on (broad-market gauges).
POPULAR_ETFS = ["SPY", "QQQ", "VOO", "IWM", "DIA", "VTI"]


def _cfg() -> dict:
    return (load_watchlist().get("market_highlights") or {})


def _already_sent(c, key: str) -> bool:
    return c.execute(
        "SELECT 1 FROM alerts WHERE kind='MKT_SENT' AND symbol=? "
        "AND created_at >= datetime('now','-1 day') LIMIT 1", (key,),
    ).fetchone() is not None


def _mark(c, key: str) -> None:
    c.execute("INSERT INTO alerts (symbol, kind, message) VALUES (?, 'MKT_SENT', '')", (key,))


def run_once(force: bool = False) -> dict:
    cfg = _cfg()
    if cfg.get("market_hours_only", True) and not force:
        try:
            from dk.util import session
            if not (session.is_trading_day() and (session.is_premarket() or session.is_rth())):
                return {"skipped": "off-hours"}
        except Exception:
            pass

    n_movers = int(cfg.get("max_movers", 6))
    n_active = int(cfg.get("max_active", 6))
    n_etf = int(cfg.get("max_etfs", 6))
    n_news = int(cfg.get("max_news", 5))

    # ---- Movers (market-wide) ----
    gainers, losers, actives = [], [], []
    try:
        for m in market_movers.fetch_movers():
            b = m.get("bucket")
            if b == "day_gainers":
                gainers.append(m)
            elif b == "day_losers":
                losers.append(m)
            elif b == "most_actives":
                actives.append(m)
    except Exception as e:
        print(f"[highlights] movers: {e}")
    gainers.sort(key=lambda m: (m.get("change_pct") or 0), reverse=True)
    losers.sort(key=lambda m: (m.get("change_pct") or 0))

    # ---- ETFs (biggest moves + popular gauges) ----
    etfs = []
    try:
        etfs = leaderboards.top_etfs()
    except Exception as e:
        print(f"[highlights] etfs: {e}")
    etf_movers = sorted([e for e in etfs if e.get("change_pct") is not None],
                        key=lambda e: abs(e["change_pct"]), reverse=True)
    etf_by_sym = {e["symbol"]: e for e in etfs}

    lines = []
    with sqlite3.connect(DB_PATH) as c:
        c.row_factory = sqlite3.Row
        mood = c.execute(
            "SELECT composite, label FROM market_sentiment ORDER BY snapshot_ts DESC LIMIT 1"
        ).fetchone()
        hdr = "🌍 Market Highlights"
        if mood:
            hdr += f"  ·  Mood {mood[0]:.0f}/100 ({mood[1]})"
        lines.append(hdr)

        if gainers:
            lines.append("\n🚀 Top gainers:")
            for m in gainers[:n_movers]:
                lines.append(f"• {m['symbol']} {m.get('change_pct',0):+.1f}% "
                             f"(${m.get('price') or 0:,.2f}) → {_lk.tradingview(m['symbol'])}")
        if losers:
            lines.append("\n📉 Top losers:")
            for m in losers[:n_movers]:
                lines.append(f"• {m['symbol']} {m.get('change_pct',0):+.1f}% "
                             f"(${m.get('price') or 0:,.2f}) → {_lk.tradingview(m['symbol'])}")
        if actives:
            lines.append("\n🔥 Most active (popular):")
            for m in actives[:n_active]:
                lines.append(f"• {m['symbol']} {m.get('change_pct',0):+.1f}% "
                             f"(${m.get('price') or 0:,.2f})")

        # ETF section: biggest movers + popular gauges
        if etf_movers or etf_by_sym:
            lines.append("\n📊 ETF highlights:")
            for e in etf_movers[:n_etf]:
                lines.append(f"• {e['symbol']} {e['change_pct']:+.2f}% — {e.get('name','')[:26]}")
            pop = [etf_by_sym[s] for s in POPULAR_ETFS if s in etf_by_sym
                   and etf_by_sym[s].get("change_pct") is not None]
            if pop:
                lines.append("  Popular: " + " · ".join(
                    f"{e['symbol']} {e['change_pct']:+.2f}%" for e in pop))

        # ---- Real-world highlights: macro events + major market-wide news ----
        macro = c.execute(
            """SELECT event_date, category, title FROM macro_events
               WHERE event_date BETWEEN date('now') AND date('now','+3 days')
                 AND importance >= 2 ORDER BY event_date LIMIT 5"""
        ).fetchall()
        if macro:
            lines.append("\n🗓️ On the macro calendar:")
            for r in macro:
                lines.append(f"• {r['event_date']} — {r['category']}: {str(r['title'])[:50]}")

        news = c.execute(
            """SELECT id, symbol, title, url, sentiment FROM news
               WHERE is_breaking=1 AND fetched_at >= datetime('now','-3 hours')
               ORDER BY ABS(COALESCE(sentiment,0)) DESC, fetched_at DESC LIMIT 40"""
        ).fetchall()
        fresh_news = [r for r in news if not _already_sent(c, f"mkt::{r['id']}")]
        if fresh_news:
            lines.append("\n⚡ Real-world highlights:")
            for r in fresh_news[:n_news]:
                tag = f"{r['symbol']}: " if r["symbol"] else ""
                url = r["url"] or ""
                lines.append(f"• {tag}{str(r['title'])[:85]}" + (f"\n  {url}" if url else ""))

        if len(lines) <= 1:
            return {"skipped": "nothing to highlight"}

        body = "\n".join(lines)
        sent = _sms._send(body) if _sms.is_configured() else False
        if sent:
            for r in fresh_news[:n_news]:
                _mark(c, f"mkt::{r['id']}")
            c.commit()

    return {"sent": bool(sent), "gainers": len(gainers), "losers": len(losers),
            "actives": len(actives), "etfs": len(etfs), "news": len(fresh_news)}
