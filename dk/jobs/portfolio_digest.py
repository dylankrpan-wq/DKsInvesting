"""Named-portfolio reports -> phone/group.

Each portfolio in config/portfolios.yaml gets its own scheduled pulse on its own
interval: top movers, forming bullish setups (backtested), and fresh news — with
tap-through links. A single dispatcher (run_due) fires whichever portfolios are
due, so any number of portfolios with different intervals just works.
"""
from __future__ import annotations
import sqlite3
from datetime import datetime, timezone
import yaml
from dk.config import CONFIG_DIR, DB_PATH
from dk.indicators import signals as _sig
from dk.analysis import backtest as _bt
from dk.notify import sms as _sms
from dk.util import links as _lk

BULL_CODES = ["MACD_BULL_CROSS", "SMA50_RECLAIM", "BB_BREAKOUT_UP", "NEW_52W_HIGH",
              "GOLDEN_CROSS", "RSI_EXIT_OVERSOLD", "RSI_OVERSOLD"]


def load_portfolios() -> dict:
    path = CONFIG_DIR / "portfolios.yaml"
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return (yaml.safe_load(f) or {}).get("portfolios") or {}


def all_portfolio_tickers() -> list[str]:
    out: list[str] = []
    for p in load_portfolios().values():
        for t in (p.get("tickers") or []):
            u = str(t).upper()
            if u not in out:
                out.append(u)
    return out


def _last_run(c, pid: str):
    r = c.execute("SELECT MAX(created_at) FROM alerts WHERE kind='PF_RUN' AND symbol=?",
                  (pid,)).fetchone()
    return r[0] if r else None


def _mins_since(ts: str | None) -> float:
    if not ts:
        return 1e9
    try:
        t = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - t).total_seconds() / 60
    except Exception:
        return 1e9


def _already_sent(c, key: str) -> bool:
    return c.execute("SELECT 1 FROM alerts WHERE kind='PF_ITEM' AND symbol=? "
                     "AND created_at >= datetime('now','-1 day') LIMIT 1",
                     (key,)).fetchone() is not None


def run_portfolio(pid: str, pcfg: dict, force: bool = False) -> dict:
    if pcfg.get("market_hours_only", True) and not force:
        try:
            from dk.util import session
            if not (session.is_trading_day() and (session.is_premarket() or session.is_rth())):
                return {"skipped": "off-hours"}
        except Exception:
            pass

    tickers = [str(t).upper() for t in (pcfg.get("tickers") or [])]
    if not tickers:
        return {"skipped": "no tickers"}
    name = pcfg.get("name", pid)
    max_setups = int(pcfg.get("max_setups", 8))
    max_news = int(pcfg.get("max_news", 6))

    # Bootstrap price history for names that lack it (capped per run).
    try:
        from dk.sources import prices_yfinance
        with sqlite3.connect(DB_PATH) as _bc:
            need = [t for t in tickers if (_bc.execute(
                "SELECT COUNT(*) FROM prices WHERE symbol=?", (t,)).fetchone()[0] or 0) < 60]
        for t in need[:12]:
            try:
                prices_yfinance.fetch_prices(t)
            except Exception:
                pass
    except Exception:
        pass

    moves, setups = [], []
    with sqlite3.connect(DB_PATH) as c:
        c.row_factory = sqlite3.Row
        # Moves — latest vs prior close (show top by |chg| regardless of threshold
        # so there's always a snapshot).
        for t in tickers:
            rows = c.execute("SELECT close FROM prices WHERE symbol=? ORDER BY ts DESC LIMIT 2",
                             (t,)).fetchall()
            if len(rows) == 2 and rows[0][0] and rows[1][0]:
                chg = (rows[0][0] - rows[1][0]) / rows[1][0] * 100
                moves.append((t, chg, rows[0][0]))
        moves.sort(key=lambda x: abs(x[1]), reverse=True)

        # Setups — bullish signal + backtest
        for t in tickers:
            try:
                summ = _sig.summarize(t)
            except Exception:
                continue
            if summ["net_lean"] != "bull" or not summ["signals"]:
                continue
            codes = [s["code"] for s in summ["signals"]]
            bt = _bt.best_backtest(t, codes)
            setups.append({"symbol": t, "label": summ["signals"][0]["label"], "bt": bt})
        setups.sort(key=lambda x: (x["bt"]["win_rate"] if x["bt"] else 0), reverse=True)

        # News — tagged to portfolio tickers, recent; dedupe
        placeholders = ",".join("?" * len(tickers))
        nrows = c.execute(
            f"""SELECT id, symbol, title, url FROM news
                WHERE symbol IN ({placeholders})
                  AND fetched_at >= datetime('now','-90 minutes')
                ORDER BY is_breaking DESC, fetched_at DESC LIMIT 40""",
            tuple(tickers),
        ).fetchall()
        fresh_news = [r for r in nrows if not _already_sent(c, f"pf::{pid}::{r['id']}")]

        mood = c.execute("SELECT composite,label FROM market_sentiment "
                         "ORDER BY snapshot_ts DESC LIMIT 1").fetchone()
        hdr = f"📋 {name}"
        if mood:
            hdr += f"  ·  Mood {mood[0]:.0f}/100 ({mood[1]})"
        lines = [hdr]

        if moves:
            up = sum(1 for _, ch, _ in moves if ch > 0)
            lines.append(f"\n📈 Movers ({up}▲ {len(moves)-up}▼):")
            for t, chg, px in moves[:8]:
                arrow = "▲" if chg > 0 else "▼"
                lines.append(f"• {arrow} {t} {chg:+.1f}% (${px:,.2f}) → {_lk.tradingview(t)}")
        if setups:
            lines.append("\n🎯 Setups (backtested):")
            for s in setups[:max_setups]:
                bt = s["bt"]
                bts = (f" — {s['label']} hit {bt['win_rate']}% "
                       f"(n={bt['n']}, avg +{bt['avg_max_gain']}% in {bt['forward_days']}d)"
                       if bt else f" — {s['label']}")
                _th = _lk.app_thesis(s["symbol"])
                link = f"📊 {_lk.tradingview(s['symbol'])}" + (f"  ·  🔬 {_th}" if _th else "")
                lines.append(f"• {s['symbol']}{bts}\n  {link}")
        if fresh_news:
            lines.append("\n⚡ News:")
            for r in fresh_news[:max_news]:
                url = r["url"] or _lk.google_news(r["symbol"])
                lines.append(f"• {r['symbol']}: {str(r['title'])[:85]}\n  {url}")

        body = "\n".join(lines)
        sent = _sms._send(body) if _sms.is_configured() else False
        if sent:
            for r in fresh_news[:max_news]:
                c.execute("INSERT INTO alerts (symbol, kind, message) VALUES (?, 'PF_ITEM', '')",
                          (f"pf::{pid}::{r['id']}",))
            c.execute("INSERT INTO alerts (symbol, kind, message) VALUES (?, 'PF_RUN', ?)",
                      (pid, name))
            c.commit()
    return {"portfolio": pid, "sent": bool(sent), "movers": len(moves),
            "setups": len(setups), "news": len(fresh_news)}


def run_due() -> dict:
    """Dispatcher: run each portfolio whose interval has elapsed."""
    results = {}
    with sqlite3.connect(DB_PATH) as c:
        for pid, pcfg in load_portfolios().items():
            interval = int(pcfg.get("interval_minutes", 20))
            if _mins_since(_last_run(c, pid)) >= interval - 0.5:
                results[pid] = run_portfolio(pid, pcfg)
    return results
