"""~25-min tech/AI/energy sector digest -> phone.

Every cycle (market-hours gated) it scans the sector universe for:
  • notable price moves today
  • deals / M&A / contract / partnership headlines
  • breaking news
  • forming bullish technical setups, each annotated with a BACKTEST hit-rate
    (how that setup has historically played out on that name)

Composes one concise Telegram message and pushes it, de-duplicating items so
the same setup/headline isn't re-sent every cycle.
"""
from __future__ import annotations
import json
import sqlite3
from datetime import datetime
import yaml
from dk.config import CONFIG_DIR, DB_PATH
from dk.indicators import signals as _sig
from dk.indicators import ta as _ta
from dk.analysis import backtest as _bt
from dk.notify import sms as _sms

DEAL_KEYWORDS = [
    "acquire", "acquires", "acquisition", "to acquire", "merger", "merges",
    "buyout", "takeover", "partnership", "partners with", "joint venture",
    "wins contract", "awarded contract", "secures contract", "signs deal",
    "multiyear deal", "multi-year deal", "strategic partnership",
    "takes stake", "acquires stake", "to supply",
]

BULL_SETUP_CODES = [
    "MACD_BULL_CROSS", "SMA50_RECLAIM", "BB_BREAKOUT_UP", "NEW_52W_HIGH",
    "GOLDEN_CROSS", "RSI_EXIT_OVERSOLD", "RSI_OVERSOLD",
]


def _cfg() -> dict:
    path = CONFIG_DIR / "sector_watch.yaml"
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _universe(cfg: dict) -> list[str]:
    out: list[str] = []
    for _, names in (cfg.get("sectors") or {}).items():
        for s in (names or []):
            u = str(s).upper()
            if u not in out:
                out.append(u)
    return out


def _already_sent(c, key: str) -> bool:
    return c.execute(
        "SELECT 1 FROM alerts WHERE kind='SECTOR_SENT' AND symbol=? "
        "AND created_at >= datetime('now','-1 day') LIMIT 1", (key,),
    ).fetchone() is not None


def _mark_sent(c, key: str) -> None:
    c.execute("INSERT INTO alerts (symbol, kind, message) VALUES (?, 'SECTOR_SENT', '')", (key,))


def run_once(force: bool = False) -> dict:
    cfg = _cfg()
    dcfg = (cfg.get("sector_digest") or {})
    if dcfg.get("market_hours_only", True) and not force:
        try:
            from dk.util import session
            if not (session.is_trading_day() and (session.is_premarket() or session.is_rth())):
                return {"skipped": "off-hours"}
        except Exception:
            pass

    syms = _universe(cfg)
    if not syms:
        return {"skipped": "empty universe"}

    # Bootstrap: fetch price history for a few sector names that lack it, so
    # setups/backtests have data. Capped per cycle; over a few cycles all fill in
    # (then it's a cheap no-op since bars are cached).
    try:
        from dk.sources import prices_yfinance
        with sqlite3.connect(DB_PATH) as _bc:
            need = [s for s in syms if (_bc.execute(
                "SELECT COUNT(*) FROM prices WHERE symbol=?", (s,)).fetchone()[0] or 0) < 60]
        for s in need[:12]:
            try:
                prices_yfinance.fetch_prices(s)
            except Exception:
                pass
    except Exception as e:
        print(f"[sector_digest] bootstrap fetch: {e}")

    move_thr = float(dcfg.get("move_threshold_pct", 4.0))
    max_setups = int(dcfg.get("max_setups", 5))
    max_deals = int(dcfg.get("max_deals", 4))
    max_news = int(dcfg.get("max_news", 5))
    fwd = int(dcfg.get("backtest_forward_days", 10))
    tgt = float(dcfg.get("backtest_target_pct", 6.0))

    placeholders = ",".join("?" * len(syms))
    moves, deals, news, setups = [], [], [], []

    with sqlite3.connect(DB_PATH) as c:
        c.row_factory = sqlite3.Row

        # --- Notable moves today ---
        for sym in syms:
            rows = c.execute(
                "SELECT close FROM prices WHERE symbol=? ORDER BY ts DESC LIMIT 2", (sym,)
            ).fetchall()
            if len(rows) == 2 and rows[0][0] and rows[1][0]:
                chg = (rows[0][0] - rows[1][0]) / rows[1][0] * 100
                if abs(chg) >= move_thr:
                    moves.append((sym, chg, rows[0][0]))
        moves.sort(key=lambda x: abs(x[1]), reverse=True)

        # --- Deals / M&A headlines ---
        deal_like = " OR ".join(["lower(title) LIKE ?"] * len(DEAL_KEYWORDS))
        drows = c.execute(
            f"""SELECT symbol, title, url, id FROM news
                WHERE symbol IN ({placeholders}) AND fetched_at >= datetime('now','-6 hours')
                  AND ({deal_like})
                ORDER BY fetched_at DESC LIMIT 30""",
            (*syms, *[f"%{k}%" for k in DEAL_KEYWORDS]),
        ).fetchall()
        for r in drows:
            if not _already_sent(c, f"deal::{r['id']}"):
                deals.append(r)

        # --- Breaking news ---
        nrows = c.execute(
            f"""SELECT symbol, title, url, id FROM news
                WHERE symbol IN ({placeholders}) AND is_breaking=1
                  AND fetched_at >= datetime('now','-3 hours')
                ORDER BY fetched_at DESC LIMIT 30""",
            tuple(syms),
        ).fetchall()
        for r in nrows:
            if not _already_sent(c, f"news::{r['id']}"):
                news.append(r)

        # --- Forming bullish setups (with backtest) ---
        for sym in syms:
            try:
                summ = _sig.summarize(sym)
            except Exception:
                continue
            if summ["net_lean"] != "bull" or not summ["signals"]:
                continue
            codes = [s["code"] for s in summ["signals"]]
            fresh_key = f"setup::{sym}::{'|'.join(sorted(codes))}"
            if _already_sent(c, fresh_key):
                continue
            bt = _bt.best_backtest(sym, codes, forward_days=fwd, target_pct=tgt)
            top = summ["signals"][0]
            setups.append({"symbol": sym, "label": top["label"], "codes": codes,
                           "bt": bt, "key": fresh_key})
        # rank setups: those with a strong historical hit-rate first
        setups.sort(key=lambda x: (x["bt"]["win_rate"] if x["bt"] else 0), reverse=True)

        # --- Compose ---
        if not (moves or deals or news or setups):
            return {"skipped": "nothing new"}

        lines = ["🖥️ Tech/AI/Energy sector pulse"]
        if moves:
            lines.append("\n📈 Moves:")
            for sym, chg, px in moves[:6]:
                lines.append(f"• {sym} {chg:+.1f}% (${px:,.2f})")
        if setups:
            lines.append("\n🎯 Setups forming (backtested):")
            for s in setups[:max_setups]:
                bt = s["bt"]
                bt_str = (f" — {s['label']} hit {bt['win_rate']}% "
                          f"(n={bt['n']}, avg +{bt['avg_max_gain']}% in {bt['forward_days']}d)"
                          if bt else f" — {s['label']} (no backtest sample)")
                lines.append(f"• {s['symbol']}{bt_str}")
        if deals:
            lines.append("\n🤝 Deals/contracts:")
            for r in deals[:max_deals]:
                lines.append(f"• {r['symbol']}: {r['title'][:90]}")
        if news:
            lines.append("\n⚡ Breaking:")
            for r in news[:max_news]:
                lines.append(f"• {r['symbol']}: {r['title'][:90]}")

        body = "\n".join(lines)
        sent = _sms._send(body) if _sms.is_configured() else False

        # --- Mark everything included as sent so it isn't repeated ---
        if sent:
            for r in deals[:max_deals]:
                _mark_sent(c, f"deal::{r['id']}")
            for r in news[:max_news]:
                _mark_sent(c, f"news::{r['id']}")
            for s in setups[:max_setups]:
                _mark_sent(c, s["key"])
            c.commit()

    return {"sent": bool(sent), "moves": len(moves), "setups": len(setups),
            "deals": len(deals), "news": len(news)}
