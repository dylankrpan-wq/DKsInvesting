"""Glossary / Key panel content. Lives in the left sidebar so it can be
collapsed to a thin tab when not in use, and clicked open as a popout.
"""
from __future__ import annotations
import streamlit as st
from dk.ui import style as ui_style


def render_sidebar_glossary() -> None:
    """Render the full glossary into the sidebar."""
    st.sidebar.markdown(
        '<div style="display:flex;align-items:center;gap:10px;padding:6px 0 14px 0;">'
        '  <div style="width:30px;height:30px;border-radius:8px;'
        '       background:linear-gradient(135deg,#00d4aa,#4ea1ff);'
        '       display:grid;place-items:center;font-weight:800;color:#062019;">DK</div>'
        '  <div style="font-weight:700;font-size:16px;color:#e8ecf4;">Key & Glossary</div>'
        '</div>',
        unsafe_allow_html=True,
    )
    st.sidebar.caption("Click any section to expand. Close this panel with the « arrow at top.")

    # ---- How the system works ----
    with st.sidebar.expander(":bulb: How DK Investing works", expanded=False):
        st.markdown("""
**The flow:**
1. **Poller** pulls fresh prices, news, earnings, macro, IPOs, TradingView ratings, Reddit trends
2. **Sentiment scorer** rates every news headline (-1 bearish ↔ +1 bullish)
3. **Opportunity score** combines price momentum + volume + news velocity + sentiment + earnings proximity
4. **Alert engine** detects price moves, volume spikes, earnings windows, sentiment surges, macro events, rank jumps
5. **Discovery** mines news + Reddit for tickers outside your watchlist
6. **Themes** group constituents into baskets and aggregate their scores
7. **Dashboard** surfaces everything for one-click investigation

**Daily flow you'll fall into:**
- Open dashboard → glance at KPI strip + macro tape
- Read **Daily digest** at top of Opportunities tab
- Scan top of Opportunity ranking — anything green and unfamiliar is a discovery candidate
- Click into a row → chart popup → if interesting, switch to **Thesis** tab for full deep-dive
- Drop a note in the journal so you remember why you're watching
""")

    # ---- Opportunity score ----
    with st.sidebar.expander(":dart: Opportunity score components", expanded=False):
        st.markdown("""
**Score (0–100)** — composite signal. Higher = more attention-worthy. **Not** a buy/sell call.

| Component | Weight | What it measures |
|---|---|---|
| **price mom** | 25% | Blended 1d/5d/20d return, normalized by ticker's own volatility |
| **vol mom** | 15% | Latest volume vs 20-day avg, log-scaled (1×=0, 2×=0.5, 4×=1.0) |
| **news vel** | 15% | 24h news count vs 7-day baseline |
| **sentiment** | 30% | Recency-weighted avg of last 24h news sentiment |
| **earn prox** | 15% | Boost when earnings within 7 days |

**Direction** = sign of (price mom + sentiment):
- **bull** = constructive lean (likely going up)
- **bear** = defensive lean (likely going down)
- **flat** = mixed signals

Each component is clipped to [-1, +1], then weighted, then magnitude × 100 = final score.
""")

    # ---- Alert types ----
    with st.sidebar.expander(":rotating_light: Alert types", expanded=False):
        st.markdown("""
| Kind | Triggers when |
|---|---|
| **PRICE_MOVE** | Daily move ≥ 5% (configurable) |
| **VOLUME_SPIKE** | Latest volume ≥ 3× the 20-day average |
| **EARNINGS_NEAR** | Earnings report within 7 days |
| **SENTIMENT_SURGE** | 24h avg news sentiment crosses ±0.6 across ≥3 articles |
| **MACRO_NEAR** | High-importance macro event (FOMC, CPI, NFP) within 3 days |
| **CRYPTO_MOVE** | Crypto 24h change ≥ 5% |
| **CRYPTO_SPIKE** | A Blofin perp moves ≥ threshold in a short window (e.g. +6%/3min) — fast pump/dump, sub-minute scan |
| **CONVICTION_LONG / SHORT** | Multiple bullish/bearish signals converging on one name (radar convergence) |
| **RANK_JUMP** | Ticker climbs ≥3 ranks AND current score ≥35 |
| **SCORE_SURGE** | Opportunity score gains ≥10 points between snapshots |
| **NEW_TOP** | Ticker enters top 5 from outside |
| **CUSTOM** | Your user-defined trigger (Tools → Custom alerts) |
| **TRADINGVIEW** | Webhook from a TradingView Pro+ alert |

All thresholds editable in `config/watchlist.yaml`. Each alert dedupes per (ticker, kind, day).
""")

    # ---- Technical indicators ----
    with st.sidebar.expander(":bar_chart: Technical indicators", expanded=False):
        st.markdown("""
| Indicator | What it tells you |
|---|---|
| **RSI(14)** | Momentum oscillator 0–100. **>70 overbought**, **<30 oversold**. |
| **MACD(12,26,9)** | Trend follower. Histogram > 0 = bullish, < 0 = bearish. |
| **SMA20/50/200** | Simple moving averages. Price above = uptrend. SMA20>SMA50>SMA200 = strong uptrend. |
| **EMA12/26** | Exponential MAs (recent prices weighted heavier). |
| **Bollinger Bands** | Price envelope ±2 std dev around SMA20. Touching upper = stretched up; lower = stretched down. |
| **ATR(14)** | Average True Range — how much the stock moves in dollars per day. Used for stop-loss sizing. |
| **VWAP** | Volume-weighted average price (intraday only). |
| **52w high/low** | Highest/lowest close in last 252 trading days. |
""")

    # ---- Sentiment indicators ----
    with st.sidebar.expander(":newspaper: Sentiment metrics", expanded=False):
        st.markdown("""
- **avg_24h** — average news-headline sentiment in the last 24 hours
- **avg_7d** — same over 7 days
- **slope_7d** — daily-avg sentiment trend over 7 days (positive = improving)
- **momentum** — avg_24h minus prior 6-day avg (recent shift)
- **velocity** — 24h article count divided by 7-day baseline
- **bull / bear %** — share of articles >+0.05 vs <−0.05
- **sources** — number of unique news outlets covering the ticker
""")

    # ---- Chart studio POVs ----
    with st.sidebar.expander(":mag: Chart Studio POVs", expanded=False):
        st.markdown("""
Different lenses on the same chart:

- **Price** — clean, just the candles/line
- **+ Sentiment overlay** — dotted gold line on secondary axis showing 3-day rolling sentiment. Confirms or contradicts price action.
- **+ News density** — vertical azure bars wherever news clusters happened. Spot the days the press paid attention.
- **+ Earnings markers** — dashed amber verticals at every earnings date in the period
- **Relative vs SPY** — top: ticker and SPY both indexed to 100. Bottom: alpha bars (positive = outperforming).
""")

    # ---- Themes ----
    with st.sidebar.expander(":rocket: Theme packs", expanded=False):
        st.markdown("""
Curated baskets (Schwab-style) that group related tickers.

**Aggregate metrics shown:**
- **score** = avg of constituent DK scores
- **sentiment** = avg of constituent 24h news sentiment
- **1d %** = avg of constituent daily moves
- **leader** = highest-scoring constituent

**The "why"** — recent strong-sentiment news pulled across all constituents in the basket.

Edit `config/themes.yaml` to add/edit themes or change constituents.
""")

    # ---- Macro context ----
    with st.sidebar.expander(":globe_with_meridians: Macro context strip", expanded=False):
        st.markdown("""
The 6 cards below the KPI strip are the **macro tape** — read every alert against this:

| Card | What it tells you |
|---|---|
| **VIX** | Fear gauge. Above 20 = elevated; below 14 = complacent |
| **US 10Y yield** | Rate regime. Higher = headwind for growth/long-duration assets |
| **DXY** | Dollar strength. Strong dollar pressures commodities + EM stocks |
| **WTI crude** | Energy + inflation tell |
| **Gold** | Risk-off proxy. Often inverse to dollar |
| **S&P 500** | Broad market context |

A +5% move on a name during a -VIX day is different from one during market panic.
""")

    # ---- Trending sources ----
    with st.sidebar.expander(":fire: Trending discovery sources", expanded=False):
        st.markdown("""
**Where DK looks for new ideas outside your watchlist:**

- **Reddit r/wallstreetbets** — retail buzz; can spot momentum early
- **Reddit r/stocks** — slightly more thoughtful; less noise
- **StockTwits trending** — currently rate-limited (HTTP 403); will reactivate when their public API stabilizes
- **News mention scanner** — extracts $TICKER and (NYSE: X) patterns from headlines you've already pulled
- **SEC EDGAR S-1 filings** — surfaces IPO-stage candidates before they're public

Tickers showing up across **multiple sources** are stronger signals than single-source noise.
""")

    # ---- Visual symbols ----
    with st.sidebar.expander(":eyes: Symbols & badges", expanded=False):
        st.markdown("""
| Symbol | Meaning |
|---|---|
| **✓ OWNED** | You hold this ticker in a connected broker |
| **▲N** | Climbed N ranks vs last snapshot |
| **▼N** | Dropped N ranks |
| **+** *(green)* | Positive sentiment (>+0.05) |
| **−** *(red)* | Negative sentiment (<−0.05) |
| **·** | Neutral (between -0.05 and +0.05) |
| **:rocket:** | Theme / discovery callout |
| **:lock:** | You own this position |
| **🔥** | Custom alert has fired |
""")

    # ---- Acronyms ----
    with st.sidebar.expander(":abc: Acronyms", expanded=False):
        st.markdown("""
| Acronym | Meaning |
|---|---|
| **ATR** | Average True Range — daily volatility in dollars |
| **BB** | Bollinger Bands |
| **CPI** | Consumer Price Index — inflation print, market-moving |
| **CSP** | Cash-Secured Put |
| **DCF** | Discounted Cash Flow |
| **DD** | Due Diligence |
| **DXY** | US Dollar Index |
| **EMA** | Exponential Moving Average |
| **EPS** | Earnings Per Share |
| **ER** | Earnings Report |
| **ETF** | Exchange-Traded Fund |
| **FOMC** | Federal Open Market Committee — Fed rate-setting body |
| **GLP-1** | Glucagon-like peptide-1 (weight-loss drug class) |
| **IPO** | Initial Public Offering |
| **MA** | Moving Average |
| **MACD** | Moving Average Convergence Divergence |
| **NFP** | Nonfarm Payrolls — monthly US jobs report |
| **OHLC** | Open / High / Low / Close |
| **POV** | Point of View — chart lens |
| **R:R** | Reward-to-Risk ratio |
| **RSI** | Relative Strength Index (0-100) |
| **SEP** | Summary of Economic Projections (Fed dot-plot) |
| **SMA** | Simple Moving Average |
| **SMR** | Small Modular Reactor |
| **SPX** | S&P 500 index |
| **TV** | TradingView |
| **VIX** | CBOE Volatility Index |
| **VWAP** | Volume-Weighted Average Price |
| **WSB** | r/wallstreetbets subreddit |
""")

    # ---- Tips ----
    with st.sidebar.expander(":bulb: Power-user tips", expanded=False):
        st.markdown("""
- **Click any row** in Opportunities/Watchlist/Discover/Sentiment/Crypto/Themes-constituents → chart popup with stats + setup notes
- **Save chart presets** — set up your perfect chart config once, name it, reload anytime
- **Custom alerts** (Tools tab) — define price/RSI/sentiment triggers without editing YAML
- **Position sizing** (Tools tab) — turns "ASTS looks good" into "buy 47 shares, stop $69, risk $300"
- **Notes journal** (bottom of Thesis tab) — write conviction notes that survive across sessions
- **Themes → drill in** — see which constituents are dragging or boosting the basket score
- **Compare tickers** (Tools tab) — overlay 2-5 tickers to spot rotation
- **Heatmap** (Tools tab) — Bloomberg-style at-a-glance view, sized by dollar volume
""")

    # ---- System info ----
    st.sidebar.markdown('<div class="sidebar-section-title" style="margin-top:20px;">SYSTEM</div>',
                         unsafe_allow_html=True)
    st.sidebar.markdown(
        f"<div style='color:#8b95ad;font-size:12px;line-height:1.8;'>"
        f"DB: <code style='color:#8b95ad;'>data/dk.db</code><br>"
        f"Watchlist: <code style='color:#8b95ad;'>config/watchlist.yaml</code><br>"
        f"Themes: <code style='color:#8b95ad;'>config/themes.yaml</code>"
        f"</div>",
        unsafe_allow_html=True,
    )
