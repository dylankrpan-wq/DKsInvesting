"""Thesis generator — produces a structured deep-dive for any symbol.

Default: deterministic template using indicators + sentiment + earnings + score.
Optional: if ANTHROPIC_API_KEY is set, Claude rewrites the verdict + risks into
prose for richer narrative. Template fallback always works.
"""
from __future__ import annotations
import sqlite3
from dataclasses import dataclass, field, asdict
from datetime import date
import yfinance as yf
from dk.config import DB_PATH
from dk import llm
from dk.opportunity.score import score_symbol
from dk.indicators import ta as ta_mod
from dk.indicators import sentiment_ind


@dataclass
class Thesis:
    symbol: str
    company: str = ""
    sector: str = ""
    market_cap: float | None = None
    last_close: float | None = None
    score: float = 0.0
    direction: str = "?"
    verdict: str = ""
    catalysts: list[dict] = field(default_factory=list)
    technicals: dict = field(default_factory=dict)
    sentiment: dict = field(default_factory=dict)
    earnings: dict = field(default_factory=dict)
    risks: list[str] = field(default_factory=list)
    narrative: str = ""

    def to_dict(self):
        return asdict(self)


def _company_meta(symbol: str) -> tuple[str, str, float | None]:
    try:
        t = yf.Ticker(symbol)
        info = t.info or {}
        name = info.get("shortName") or info.get("longName") or symbol
        sector = info.get("sector") or "?"
        mcap = info.get("marketCap")
        return name, sector, float(mcap) if mcap else None
    except Exception:
        return symbol, "?", None


def _next_earnings(c, symbol: str) -> tuple[str | None, int | None]:
    row = c.execute(
        "SELECT report_date FROM earnings WHERE symbol=? AND report_date >= date('now') ORDER BY report_date ASC LIMIT 1",
        (symbol,),
    ).fetchone()
    if not row:
        return None, None
    rd = row[0]
    try:
        d = date.fromisoformat(rd[:10])
        return rd[:10], (d - date.today()).days
    except Exception:
        return rd, None


def _top_catalysts(c, symbol: str, limit: int = 3) -> list[dict]:
    rows = c.execute(
        """SELECT title, url, source, sentiment, published, fetched_at
           FROM news WHERE symbol=? AND sentiment IS NOT NULL
             AND fetched_at >= datetime('now', '-7 days')
           ORDER BY sentiment DESC LIMIT ?""",
        (symbol, limit),
    ).fetchall()
    return [{"title": r[0], "url": r[1], "source": r[2],
             "sentiment": r[3], "published": r[4]} for r in rows]


def _technicals_summary(snap) -> dict:
    return {
        "trend": snap.trend,
        "rsi14": snap.rsi14,
        "macd_hist": snap.macd_hist,
        "bb_pos": snap.bb_pos,
        "vol_ratio_20d": snap.vol_ratio_20d,
        "pct_off_52w_high": snap.pct_off_52w_high,
        "pct_above_52w_low": snap.pct_above_52w_low,
        "sma20": snap.sma20, "sma50": snap.sma50, "sma200": snap.sma200,
        "notes": snap.setup_notes,
    }


def _sentiment_summary(snap) -> dict:
    return {
        "avg_24h": snap.avg_24h,
        "avg_7d": snap.avg_7d,
        "slope_7d": snap.slope_7d,
        "momentum": snap.momentum,
        "velocity": snap.velocity,
        "article_count_24h": snap.article_count_24h,
        "bull_pct": snap.bull_pct,
        "bear_pct": snap.bear_pct,
        "unique_sources_7d": snap.unique_sources_7d,
        "top_bull": snap.top_bull,
        "top_bear": snap.top_bear,
    }


def _verdict(score: float, direction: str, ta_snap, senti, earn_days: int | None) -> str:
    parts = []
    if score >= 50:
        parts.append("**Worth watching closely** —")
    elif score >= 30:
        parts.append("**On the radar** —")
    else:
        parts.append("Quiet for now —")

    if direction == "bull":
        parts.append("constructive lean")
    elif direction == "bear":
        parts.append("defensive lean")
    else:
        parts.append("flat lean")

    if ta_snap.trend == "up":
        parts.append("with price riding above 20/50 SMAs")
    elif ta_snap.trend == "down":
        parts.append("but trend below short-term MAs")

    if senti and senti.momentum and senti.momentum > 0.15:
        parts.append("• news tone improving")
    elif senti and senti.momentum and senti.momentum < -0.15:
        parts.append("• news tone deteriorating")

    if earn_days is not None and earn_days <= 7:
        parts.append(f"• earnings in {earn_days}d (catalyst)")

    if ta_snap.rsi14 is not None and ta_snap.rsi14 >= 70:
        parts.append("• RSI overbought — chase risk")
    elif ta_snap.rsi14 is not None and ta_snap.rsi14 <= 30:
        parts.append("• RSI oversold — possible bounce setup")

    return " ".join(parts) + "."


def _risks(ta_snap, senti, earn_days: int | None) -> list[str]:
    risks: list[str] = []
    if ta_snap.rsi14 is not None and ta_snap.rsi14 >= 75:
        risks.append(f"RSI {ta_snap.rsi14:.0f} — extended; pullback risk")
    if ta_snap.pct_off_52w_high is not None and -2 <= ta_snap.pct_off_52w_high <= 0:
        risks.append("At 52-week high — resistance / profit-taking risk")
    if ta_snap.bb_pos is not None and ta_snap.bb_pos >= 0.95:
        risks.append("Pinned to upper Bollinger — mean-reversion risk")
    if senti and senti.bear_pct and senti.bear_pct > 30:
        risks.append(f"{senti.bear_pct:.0f}% of recent articles negative")
    if senti and senti.top_bear:
        risks.append(f"Negative headline: \"{senti.top_bear['title'][:90]}\"")
    if earn_days is not None and earn_days <= 3:
        risks.append(f"Earnings in {earn_days}d — binary event risk")
    if ta_snap.atr14 and ta_snap.last_close:
        atr_pct = ta_snap.atr14 / ta_snap.last_close * 100
        if atr_pct > 5:
            risks.append(f"High volatility (ATR {atr_pct:.1f}% of price)")
    return risks or ["No standout near-term risk flags."]


def _maybe_claude_narrative(thesis: Thesis) -> str | None:
    """Optional: enrich verdict + risks with Claude prose if API key is set."""
    prompt = f"""You are a sharp equity analyst writing for an experienced trader.
Write a 4-6 sentence narrative thesis for {thesis.symbol} ({thesis.company}, sector: {thesis.sector}).
Frame it as an opportunity-discovery note, NOT a buy/sell recommendation.

Score: {thesis.score:.1f}/100 ({thesis.direction})
Trend: {thesis.technicals.get('trend')}
RSI(14): {thesis.technicals.get('rsi14')}
% off 52w high: {thesis.technicals.get('pct_off_52w_high')}
News sentiment 24h avg: {thesis.sentiment.get('avg_24h')}
News momentum (24h - prior 6d): {thesis.sentiment.get('momentum')}
Articles in last 24h: {thesis.sentiment.get('article_count_24h')}
Top recent positive headline: {thesis.catalysts[0]['title'] if thesis.catalysts else 'none'}
Top recent negative headline: {(thesis.sentiment.get('top_bear') or {}).get('title', 'none')}
Earnings: {thesis.earnings}

Be specific. No hedging filler. End with one sentence on what to watch next."""
    result = llm.complete(prompt, model="claude-haiku-4-5", max_tokens=400)
    return result.get("text") if result else None


def build(symbol: str) -> Thesis:
    name, sector, mcap = _company_meta(symbol)
    ta_snap = ta_mod.compute(symbol)
    senti_snap = sentiment_ind.compute(symbol)

    with sqlite3.connect(DB_PATH) as c:
        opp = score_symbol(c, symbol)
        catalysts = _top_catalysts(c, symbol)
        next_er, days_out = _next_earnings(c, symbol)

    earnings_dict = {"next_date": next_er, "days_out": days_out}
    verdict = _verdict(opp.score, opp.direction, ta_snap, senti_snap, days_out)
    risks = _risks(ta_snap, senti_snap, days_out)

    thesis = Thesis(
        symbol=symbol,
        company=name,
        sector=sector,
        market_cap=mcap,
        last_close=ta_snap.last_close,
        score=opp.score,
        direction=opp.direction,
        verdict=verdict,
        catalysts=catalysts,
        technicals=_technicals_summary(ta_snap),
        sentiment=_sentiment_summary(senti_snap),
        earnings=earnings_dict,
        risks=risks,
    )

    # Try optional Claude narrative
    narrative = _maybe_claude_narrative(thesis)
    if narrative:
        thesis.narrative = narrative
    else:
        thesis.narrative = _template_narrative(thesis)

    return thesis


def _template_narrative(t: Thesis) -> str:
    lines = [
        f"## {t.symbol} — {t.company}",
        f"*{t.sector}* · market cap "
        f"{('$' + (str(round(t.market_cap/1e9,1)) + 'B') if t.market_cap and t.market_cap >= 1e9 else (('$' + str(round((t.market_cap or 0)/1e6,0)) + 'M') if t.market_cap else 'n/a'))}"
        f" · last close {('$' + format(t.last_close, ',.2f')) if t.last_close else 'n/a'}",
        "",
        f"**Opportunity score: {t.score:.1f} / 100 ({t.direction})**",
        "",
        t.verdict,
        "",
        "### Recent catalysts",
    ]
    if t.catalysts:
        for c in t.catalysts:
            score = c.get("sentiment")
            score_txt = f" *(score {score:+.2f})*" if score is not None else ""
            lines.append(f"- [{c['title']}]({c['url']}) — {c.get('source','')}{score_txt}")
    else:
        lines.append("- *No high-sentiment catalysts in last 7 days.*")

    lines += ["", "### Technical setup"]
    tech = t.technicals
    lines.append(f"- Trend: **{tech.get('trend')}**")
    if tech.get("rsi14") is not None:
        lines.append(f"- RSI(14): {tech['rsi14']:.1f}")
    if tech.get("macd_hist") is not None:
        lines.append(f"- MACD histogram: {tech['macd_hist']:+.3f}")
    if tech.get("bb_pos") is not None:
        lines.append(f"- Bollinger position: {tech['bb_pos']:.2f}  *(0=lower band, 1=upper band)*")
    if tech.get("pct_off_52w_high") is not None:
        lines.append(f"- {tech['pct_off_52w_high']:+.1f}% from 52-week high")
    if tech.get("vol_ratio_20d") is not None:
        lines.append(f"- Volume vs 20d avg: {tech['vol_ratio_20d']:.2f}x")
    if tech.get("notes"):
        lines.append("")
        for n in tech["notes"]:
            lines.append(f"  - {n}")

    lines += ["", "### Sentiment posture"]
    s = t.sentiment
    if s.get("avg_24h") is not None:
        lines.append(f"- 24h avg sentiment: **{s['avg_24h']:+.2f}** (over {s['article_count_24h']} articles)")
    if s.get("avg_7d") is not None:
        lines.append(f"- 7d avg sentiment: {s['avg_7d']:+.2f}")
    if s.get("slope_7d") is not None:
        direction = "improving" if s["slope_7d"] > 0 else "deteriorating"
        lines.append(f"- 7d slope: {s['slope_7d']:+.3f}/day ({direction})")
    if s.get("momentum") is not None:
        lines.append(f"- Momentum (24h vs prior 6d): {s['momentum']:+.2f}")
    if s.get("bull_pct") is not None and s.get("bear_pct") is not None:
        lines.append(f"- Breadth: {s['bull_pct']:.0f}% bull / {s['bear_pct']:.0f}% bear")
    if s.get("top_bull"):
        lines.append(f"- Top bull headline: [{s['top_bull']['title']}]({s['top_bull']['url']}) ({s['top_bull']['score']:+.2f})")
    if s.get("top_bear"):
        lines.append(f"- Top bear headline: [{s['top_bear']['title']}]({s['top_bear']['url']}) ({s['top_bear']['score']:+.2f})")

    lines += ["", "### Earnings"]
    e = t.earnings
    if e.get("next_date"):
        lines.append(f"- Next report: **{e['next_date']}** ({e.get('days_out')} days out)")
    else:
        lines.append("- No scheduled earnings on file.")

    lines += ["", "### Risks"]
    for r in t.risks:
        lines.append(f"- {r}")

    return "\n".join(lines)
