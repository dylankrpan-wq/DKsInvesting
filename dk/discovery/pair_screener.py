"""Crypto-inclusive pair-trade / statistical-arbitrage screener.

Adapts the pair-trade-screener skill to DK Investing's free stack: prices come
from yfinance (covers crypto AND equities, no key), cointegration via
statsmodels Engle-Granger. Screens economically-sensible groups only (crypto
majors, crypto-proxy equities vs the coins, semis, mega-tech) rather than all
cross-asset pairs, so results aren't spurious.

Market-neutral framing — surfaces relative-value setups to investigate, never
prescriptive trade instructions. Crypto trades 24/7 and equities don't, so each
pair is aligned on its shared dates before testing.

Run:  uv run python -m dk.discovery.pair_screener
"""
from __future__ import annotations
import itertools
import warnings
from dataclasses import dataclass, asdict
from datetime import date

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")  # statsmodels/yfinance chatter

# Groups of comparable assets. Pairs are only formed WITHIN a group (plus the
# explicit cross pairs below), so we never test e.g. NVDA vs XRP.
GROUPS: dict[str, list[str]] = {
    "crypto_majors": ["BTC-USD", "ETH-USD", "XRP-USD", "SOL-USD",
                      "BNB-USD", "LTC-USD", "DOGE-USD"],
    "crypto_proxy_equities": ["MSTR", "COIN", "IBIT", "ETHE"],
    "semis": ["NVDA", "AMD", "MU", "INTC"],
    "mega_tech": ["AAPL", "MSFT", "GOOGL", "META"],
}
# Cross-group pairs that are economically meaningful (proxy vs the coin it tracks).
CROSS_PAIRS: list[tuple[str, str]] = [
    ("MSTR", "BTC-USD"), ("COIN", "BTC-USD"), ("COIN", "ETH-USD"),
    ("IBIT", "BTC-USD"), ("ETHE", "ETH-USD"), ("MSTR", "COIN"),
]

MIN_OVERLAP = 90          # min shared daily points to test a pair
MIN_ABS_CORR = 0.55       # returns-correlation gate (crypto pairs run high)
COINT_P_MAX = 0.10        # Engle-Granger p to be considered cointegrated
ENTRY_Z = 2.0
WATCH_Z = 1.5


@dataclass
class PairResult:
    pair: str
    a: str
    b: str
    group: str
    corr: float            # daily-returns Pearson
    beta: float            # OLS hedge ratio (A on B)
    coint_p: float         # Engle-Granger p-value
    half_life_days: float  # AR(1) mean-reversion half-life
    zscore: float          # current spread z (full-window)
    n: int                 # overlapping observations
    signal: str
    strength: str

    def as_row(self) -> dict:
        return asdict(self)


def _fetch_closes(symbols: list[str], period: str = "1y") -> pd.DataFrame:
    import yfinance as yf
    data = yf.download(symbols, period=period, interval="1d",
                       auto_adjust=True, progress=False, group_by="ticker")
    closes = {}
    for s in symbols:
        try:
            if isinstance(data.columns, pd.MultiIndex):
                col = data[s]["Close"]
            else:  # single symbol fallback
                col = data["Close"]
            if col.notna().sum() >= MIN_OVERLAP:
                closes[s] = col
        except Exception:
            continue
    if not closes:
        return pd.DataFrame()
    return pd.DataFrame(closes)


def _half_life(spread: np.ndarray) -> float:
    """AR(1) mean-reversion half-life in observations."""
    lag = spread[:-1]
    delta = np.diff(spread)
    lag_c = np.vstack([lag, np.ones(len(lag))]).T
    try:
        coef, _, _, _ = np.linalg.lstsq(lag_c, delta, rcond=None)
        k = coef[0]
        if k >= 0:
            return float("inf")  # not mean-reverting
        return float(-np.log(2) / np.log(1 + k))
    except Exception:
        return float("inf")


def _analyze_pair(a: str, b: str, group: str,
                  closes: pd.DataFrame) -> PairResult | None:
    if a not in closes.columns or b not in closes.columns:
        return None
    df = closes[[a, b]].dropna()
    if len(df) < MIN_OVERLAP:
        return None
    pa, pb = df[a].to_numpy(), df[b].to_numpy()

    rets = df.pct_change().dropna()
    corr = float(rets[a].corr(rets[b]))
    if not np.isfinite(corr) or abs(corr) < MIN_ABS_CORR:
        return None

    # OLS hedge ratio: A = alpha + beta*B
    X = np.vstack([pb, np.ones(len(pb))]).T
    beta, alpha = np.linalg.lstsq(X, pa, rcond=None)[0]
    spread = pa - (beta * pb + alpha)

    from statsmodels.tsa.stattools import coint
    try:
        _, coint_p, _ = coint(pa, pb)
    except Exception:
        return None

    mu, sd = spread.mean(), spread.std()
    z = float((spread[-1] - mu) / sd) if sd > 0 else 0.0
    hl = _half_life(spread)

    if abs(z) >= ENTRY_Z:
        signal = "LONG_A_SHORT_B" if z < 0 else "SHORT_A_LONG_B"
    elif abs(z) >= WATCH_Z:
        signal = "WATCH"
    else:
        signal = "NONE"

    if coint_p < 0.01:
        strength = "★★★"
    elif coint_p < 0.05:
        strength = "★★"
    elif coint_p < COINT_P_MAX:
        strength = "★"
    else:
        strength = "—"

    return PairResult(
        pair=f"{a}/{b}", a=a, b=b, group=group, corr=round(corr, 3),
        beta=round(float(beta), 3), coint_p=round(float(coint_p), 4),
        half_life_days=round(hl, 1) if np.isfinite(hl) else float("inf"),
        zscore=round(z, 2), n=len(df), signal=signal, strength=strength,
    )


def _candidate_pairs() -> list[tuple[str, str, str]]:
    out: list[tuple[str, str, str]] = []
    seen: set[frozenset] = set()
    for group, members in GROUPS.items():
        for a, b in itertools.combinations(members, 2):
            key = frozenset((a, b))
            if key not in seen:
                seen.add(key)
                out.append((a, b, group))
    for a, b in CROSS_PAIRS:
        key = frozenset((a, b))
        if key not in seen:  # don't re-list a pair already covered within a group
            seen.add(key)
            out.append((a, b, "crypto_proxy_cross"))
    return out


def screen(period: str = "1y") -> list[PairResult]:
    symbols = sorted({s for g in GROUPS.values() for s in g}
                     | {s for p in CROSS_PAIRS for s in p})
    closes = _fetch_closes(symbols, period=period)
    if closes.empty:
        return []
    results: list[PairResult] = []
    for a, b, group in _candidate_pairs():
        r = _analyze_pair(a, b, group, closes)
        if r is not None:
            results.append(r)
    # Cointegrated first, then by how stretched the spread is right now
    results.sort(key=lambda r: (r.coint_p >= COINT_P_MAX, -abs(r.zscore)))
    return results


def build_report(results: list[PairResult]) -> str:
    today = date.today().isoformat()
    coint = [r for r in results if r.coint_p < COINT_P_MAX]
    actionable = [r for r in coint if r.signal in ("LONG_A_SHORT_B", "SHORT_A_LONG_B")]
    watch = [r for r in coint if r.signal == "WATCH"]

    lines = [
        f"# Crypto-inclusive pair-trade screen — {today}",
        "",
        f"Universe: {sum(len(g) for g in GROUPS.values())} assets across "
        f"{len(GROUPS)} groups + crypto-proxy cross pairs. Source: yfinance 1y daily, "
        f"aligned per pair. Cointegration: Engle-Granger (statsmodels).",
        "",
        "**Market-neutral, relative-value setups to investigate — not trade instructions. "
        "z = how many std devs the spread sits from its own mean right now.**",
        "",
        f"- Pairs tested (passed corr gate): {len(results)}",
        f"- Cointegrated (p < {COINT_P_MAX}): {len(coint)}",
        f"- At an entry extreme (|z| >= {ENTRY_Z}): {len(actionable)}",
        f"- On watch ({WATCH_Z} <= |z| < {ENTRY_Z}): {len(watch)}",
        "",
        "## Cointegrated pairs (ranked: tradeable extremes first)",
        "",
        "| Pair | Group | corr | coint p | strength | half-life (d) | z | read |",
        "|------|-------|-----:|--------:|:--------:|-------------:|----:|------|",
    ]
    for r in coint:
        hl = "∞" if r.half_life_days == float("inf") else f"{r.half_life_days:g}"
        read = _read(r)
        lines.append(f"| {r.pair} | {r.group} | {r.corr:.2f} | {r.coint_p:.3f} | "
                     f"{r.strength} | {hl} | {r.zscore:+.2f} | {read} |")
    if not coint:
        lines.append("| _none_ | | | | | | | spreads in equilibrium — check back |")

    lines += ["", "## Not currently cointegrated (corr-only, FYI)", ""]
    noncoint = [r for r in results if r.coint_p >= COINT_P_MAX]
    if noncoint:
        lines.append("| Pair | corr | coint p | z |")
        lines.append("|------|-----:|--------:|----:|")
        for r in noncoint[:12]:
            lines.append(f"| {r.pair} | {r.corr:.2f} | {r.coint_p:.3f} | {r.zscore:+.2f} |")
    else:
        lines.append("_All correlated pairs were cointegrated._")

    lines += [
        "",
        "## Notes & caveats",
        "- IBIT/BTC and ETHE/ETH track the same underlying — high cointegration is "
        "tautological, not an edge (the spread is mostly fees/premium). Shown for completeness.",
        "- Crypto↔equity pairs are aligned on shared trading days (weekends dropped).",
        "- Half-life is the AR(1) mean-reversion speed; ∞ means the spread isn't reverting.",
        "- No borrow/shortability or funding costs modeled; verify both legs are shortable.",
        "- Correlation gate uses daily *returns*; cointegration uses *price levels*.",
    ]
    return "\n".join(lines)


def _read(r: PairResult) -> str:
    if r.signal == "LONG_A_SHORT_B":
        return f"{r.a} cheap vs {r.b} → long {r.a} / short {r.b} (β {r.beta:g})"
    if r.signal == "SHORT_A_LONG_B":
        return f"{r.a} rich vs {r.b} → short {r.a} / long {r.b} (β {r.beta:g})"
    if r.signal == "WATCH":
        side = "cheap" if r.zscore < 0 else "rich"
        return f"approaching extreme ({r.a} {side})"
    return "near equilibrium"


if __name__ == "__main__":
    import io
    import sys
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    res = screen()
    report = build_report(res)
    out = f"pair_trade_analysis_crypto_{date.today().isoformat()}.md"
    with open(out, "w", encoding="utf-8") as f:
        f.write(report)
    print(report)
    print(f"\n[saved {out}]")
