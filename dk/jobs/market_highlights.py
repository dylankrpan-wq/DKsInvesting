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
    if not force:
        from dk.notify import gate
        if not gate.should_push("highlights"):
            return {"skipped": "gated"}
    cfg = _cfg()

    # Are we in a live market session (fresh intraday equity data)? Off-session
    # (holidays/weekends/evenings) we still run, but as a NEWS + CRYPTO pulse —
    # equity movers would just be stale last-session data, so we skip those and
    # only push when there's genuinely fresh news/crypto to report.
    in_session = True
    try:
        from dk.util import session
        in_session = session.is_trading_day() and (
            session.is_premarket() or session.is_rth() or session.is_afterhours())
    except Exception:
        pass

    n_movers = int(cfg.get("max_movers", 6))
    n_active = int(cfg.get("max_active", 6))
    n_etf = int(cfg.get("max_etfs", 6))
    n_news = int(cfg.get("max_news", 5))

    # ---- Movers + ETFs (market-wide) — only meaningful in an active session ----
    gainers, losers, actives, etfs = [], [], [], []
    etf_movers, etf_by_sym = [], {}
    if in_session:
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
        try:
            etfs = leaderboards.top_etfs()
        except Exception as e:
            print(f"[highlights] etfs: {e}")
        etf_movers = sorted([e for e in etfs if e.get("change_pct") is not None],
                            key=lambda e: abs(e["change_pct"]), reverse=True)
        etf_by_sym = {e["symbol"]: e for e in etfs}

    # ---- Indices + sector rotation (in-session only — last close is stale off-hrs) ----
    idx, secs = [], []
    if in_session:
        try:
            from dk.sources import market_snapshot
            idx = market_snapshot.indices()
            secs = market_snapshot.sectors()
        except Exception as e:
            print(f"[highlights] snapshot: {e}")

    # ---- Crypto (24/7) — always available, incl. weekends/holidays/evenings ----
    crypto = []
    try:
        cr = leaderboards.top_crypto(15)
        crypto = sorted([x for x in cr if x.get("change_24h") is not None],
                        key=lambda x: abs(x["change_24h"]), reverse=True)
    except Exception as e:
        print(f"[highlights] crypto: {e}")

    lines = []
    with sqlite3.connect(DB_PATH) as c:
        c.row_factory = sqlite3.Row
        mood = c.execute(
            "SELECT composite, label FROM market_sentiment ORDER BY snapshot_ts DESC LIMIT 1"
        ).fetchone()
        hdr = "🌍 Market Highlights" if in_session else "🌙 Off-hours pulse (news + crypto)"
        if mood:
            hdr += f"  ·  Mood {mood[0]:.0f}/100 ({mood[1]})"
        lines.append(hdr)

        # Indices — the headline market read
        if idx:
            lines.append("\n📇 Indices:")
            lines.append("  " + " · ".join(
                f"{i['name']} {i['change_pct']:+.2f}%" for i in idx
                if i.get("change_pct") is not None))
        # Sector rotation — who's leading / lagging
        if len(secs) >= 4:
            lead = ", ".join(f"{s['name'].split()[0]} {s['change_pct']:+.1f}%" for s in secs[:3])
            lag = ", ".join(f"{s['name'].split()[0]} {s['change_pct']:+.1f}%" for s in secs[-3:])
            lines.append("\n🧭 Sector rotation:")
            lines.append(f"  🟢 Leading: {lead}")
            lines.append(f"  🔴 Lagging: {lag}")

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

        # ---- Crypto (always, 24/7) ----
        crypto_notable = [x for x in crypto if abs(x.get("change_24h") or 0) >= 3]
        if crypto:
            show = (crypto_notable or crypto)[:6]
            lines.append("\n🪙 Crypto (24h):")
            for x in show:
                lines.append(f"• {x['symbol']} {x.get('change_24h',0):+.1f}% "
                             f"(${x.get('price') or 0:,.4f})")

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

        # Off-session: only push when there's genuinely fresh news OR a notable
        # crypto move — avoids re-sending stale content every interval overnight.
        if not in_session and not force and not fresh_news and not crypto_notable:
            return {"skipped": "off-hours, nothing fresh"}
        if len(lines) <= 1:
            return {"skipped": "nothing to highlight"}

        body = "\n".join(lines)
        sent = _sms._send(body) if _sms.is_configured() else False
        if sent:
            for r in fresh_news[:n_news]:
                _mark(c, f"mkt::{r['id']}")
            c.commit()

    return {"sent": bool(sent), "in_session": in_session, "indices": len(idx),
            "sectors": len(secs), "gainers": len(gainers), "losers": len(losers),
            "actives": len(actives), "etfs": len(etfs), "crypto": len(crypto),
            "news": len(fresh_news)}
