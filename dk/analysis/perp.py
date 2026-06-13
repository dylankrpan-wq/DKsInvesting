"""On-demand perp structure analysis for any Blofin perpetual.

analyze(inst_id) computes the structure deterministically from live ticker +
candles + funding (no fabrication — every number is measured). template_read()
renders a grounded, defined-risk read; claude_read() writes the nuanced version
via dk.llm (key-gated, template fallback). compact_from_ticker() is a one-line
read built from ticker fields alone — cheap enough to staple onto every spike
alert without extra API calls.

Framed as opportunity discovery — both long and short sides with explicit
invalidation — never a prescriptive "do this" pick. No order-book / OI / IV
data exists here, so the reads say so.
"""
from __future__ import annotations
from datetime import datetime, timezone
from dk.sources import crypto_deriv
from dk import llm


def _fmt(p: float | None) -> str:
    if p is None:
        return "n/a"
    if p >= 1000:
        return f"{p:,.2f}"
    if p >= 1:
        return f"{p:,.4f}".rstrip("0").rstrip(".")
    return f"{p:.8f}".rstrip("0").rstrip(".")


def _pct(a: float, b: float) -> float | None:
    return (a - b) / b * 100.0 if b else None


def compact_from_ticker(t: dict, spike_pct: float | None = None,
                        window_min: int | None = None) -> str:
    """One-line read from ticker fields only — no extra API calls."""
    last, hi, lo = t["last"], t.get("high24h") or 0, t.get("low24h") or 0
    off_hi = _pct(last, hi) if hi else None
    abv_lo = _pct(last, lo) if lo else None
    spike = f"spiked {spike_pct:+.0f}% in {window_min}m; " if spike_pct is not None else ""
    if off_hi is not None and off_hi > -3:
        lean = "at 24h highs — extended, chase risk"
    elif abv_lo is not None and abv_lo < 5:
        lean = "near 24h lows — capitulation/bounce zone"
    elif off_hi is not None and abv_lo is not None:
        lean = f"mid-range ({off_hi:+.0f}% off high, {abv_lo:+.0f}% off low)"
    else:
        lean = "range read unavailable"
    rng = f" | 24h ${_fmt(lo)}–${_fmt(hi)}" if hi and lo else ""
    return f"{spike}now ${_fmt(last)} | {lean}{rng}"


def _sma(values: list[float], n: int) -> float | None:
    if len(values) < 1:
        return None
    w = values[-n:] if len(values) >= n else values
    return sum(w) / len(w)


def analyze(inst_id: str, ticker: dict | None = None) -> dict | None:
    """Full structure analysis. Returns a JSON-safe dict, or None if the pair
    has no data. Pass `ticker` (from fetch_tickers) to skip the per-pair ticker
    fetch — the scanner uses this to save a call per candidate."""
    inst_id = inst_id.strip().upper()
    if "-" not in inst_id:
        inst_id = inst_id + "-USDT"   # bare base -> USDT perp
    t = ticker or crypto_deriv.fetch_ticker(inst_id)
    if not t:
        return None
    h1 = crypto_deriv.fetch_candles(inst_id, "1H", 48)
    m15 = crypto_deriv.fetch_candles(inst_id, "15m", 16)
    funding = crypto_deriv.fetch_funding(inst_id)

    last = t["last"]
    a: dict = {
        "inst_id": inst_id,
        "as_of_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "last": last,
        "chg_24h_pct": round(t["chg_24h_pct"], 1) if t["chg_24h_pct"] is not None else None,
        "high24h": t["high24h"], "low24h": t["low24h"],
        "off_high_pct": round(_pct(last, t["high24h"]), 1) if t["high24h"] else None,
        "above_low_pct": round(_pct(last, t["low24h"]), 1) if t["low24h"] else None,
        "range24_pct": round(_pct(t["high24h"], t["low24h"]), 1) if t["low24h"] else None,
        "quote_vol_usd": round(t["quote_vol_usd"]),
        "funding_pct": round(funding * 100, 4) if funding is not None else None,
        "funding_side": (None if funding is None else
                         ("longs pay shorts" if funding > 0 else "shorts pay longs")),
    }

    # 1H macro structure
    if h1:
        closes = [c["close"] for c in h1]
        highs = [c["high"] for c in h1]
        peak = max(highs)
        peak_i = highs.index(peak)
        a["peak_1h"] = peak
        a["peak_at_utc"] = datetime.fromtimestamp(h1[peak_i]["ts"] / 1000, timezone.utc).isoformat(timespec="minutes")
        a["peak_retrace_pct"] = round(_pct(last, peak), 1)
        ma20 = _sma(closes, 20)
        a["ma20_1h"] = round(ma20, 6) if ma20 else None
        a["vs_ma_pct"] = round(_pct(last, ma20), 1) if ma20 else None

    # 15m micro structure (last ~8 bars = 2h for the working range)
    if m15:
        recent = m15[-8:]
        a["range_lo"] = min(c["low"] for c in recent)
        a["range_hi"] = max(c["high"] for c in recent)
        a["local_high"] = max(c["high"] for c in m15)
        a["local_low"] = min(c["low"] for c in m15)
        vols = [c["vol"] for c in m15]
        avgv = sum(vols) / len(vols) if vols else 0
        a["last_vol_x"] = round(vols[-1] / avgv, 1) if avgv else None
        _mnp = _pct(m15[-1]["close"], m15[0]["open"])
        a["micro_net_pct"] = round(_mnp, 1) if _mnp is not None else None
        a["rejections"] = sum(1 for c in recent if c["close"] < c["open"])

    # Position classification
    lh = a.get("local_high"); ll = a.get("local_low")
    if lh and ll:
        if last >= lh * 0.99:
            a["micro_pos"] = "testing local resistance"
        elif last <= ll * 1.01:
            a["micro_pos"] = "testing local support"
        else:
            a["micro_pos"] = "mid-range (no-man's-land)"
    retr = a.get("peak_retrace_pct")
    if retr is not None and retr <= -12:
        a["phase"] = "post-spike fade"
    elif retr is not None and retr >= -3:
        a["phase"] = "at/near recent highs"
    else:
        a["phase"] = "mid-structure"

    # Defined-risk framing (both sides). Resistance = local high, support = local low.
    res = lh or t["high24h"]
    sup = ll or t["low24h"]
    low24 = t["low24h"]
    ma = a.get("ma20_1h")
    if res and sup and res > last > 0:
        short_stop = res * 1.005
        # profit-side levels for a short, nearest→far: recent range low, 16-bar
        # low, MA (if below), 24h low. _setup filters/sorts/dedups + R-fills.
        a["short"] = _setup(last, short_stop,
                            [a.get("range_lo"), ll, ma, low24], "short")
        a["invalidation_short"] = f"close/hold above ${_fmt(res)}"
    # `sup < last` guard: without it, when sup (local/24h low) sits at/above the
    # live price on a fresh breakdown, the long stop lands ABOVE entry — an
    # inverted, nonsensical risk that also breaks the tracker's TP/stop logic.
    if sup and res and sup < last:
        long_stop = sup * 0.995
        a["long"] = _setup(last, long_stop,
                           [a.get("range_hi"), lh, ma, a.get("peak_1h"), t["high24h"]],
                           "long")
        a["invalidation_long"] = f"close/hold below ${_fmt(sup)}"

    a["caveats"] = [
        "low-float perp — manipulation-prone; a wick can liquidate either side on leverage",
        "no order-book depth / open-interest / IV in this data — price+volume+funding only",
        "volume read is a conviction hint, not confirmation",
    ]
    return a


_FILL_STEP_R = 1.5  # min R spacing for ladder rungs filled past structural levels


def _setup(entry: float, stop: float, levels: list, side: str) -> dict:
    """Build a 3-rung take-profit ladder (TP1/TP2/TP3). Rungs are real
    structural levels on the profit side, nearest first; if fewer than 3
    distinct levels exist, the rest are filled at fixed R-multiples beyond the
    last one. Each rung carries its R-multiple (reward/risk) and basis."""
    risk = abs(stop - entry)
    risk_pct = round(risk / entry * 100, 1) if entry else None
    out = {"entry": round(entry, 6), "stop": round(stop, 6), "risk_pct": risk_pct}
    # Stop must be on the correct side of entry, else the setup is invalid.
    bad_stop = (side == "short" and stop <= entry) or (side == "long" and stop >= entry)
    if not entry or risk <= 0 or bad_stop:
        out["tps"] = []
        return out

    # Structural candidates on the profit side, nearest-first, deduped ~0.4%
    if side == "short":
        cands = sorted([x for x in levels if x and x < entry], reverse=True)
    else:
        cands = sorted([x for x in levels if x and x > entry])
    struct: list[float] = []
    for x in cands:
        if not struct or abs(x - struct[-1]) / entry > 0.004:
            struct.append(x)

    def _rung(level: float, basis: str) -> dict:
        r = abs(entry - level) / risk
        return {"level": round(level, 6), "r": round(r, 1),
                "pct": round((level - entry) / entry * 100, 1), "basis": basis}

    tps = [_rung(x, "structure") for x in struct[:3]]
    # Fill to 3 rungs at R-multiples stepping >= _FILL_STEP_R beyond the last,
    # so filled rungs are always meaningfully spaced (not piled on a structural one).
    last_r = tps[-1]["r"] if tps else 0.0
    while len(tps) < 3:
        last_r += _FILL_STEP_R
        lvl = entry - last_r * risk if side == "short" else entry + last_r * risk
        if lvl <= 0:
            break
        tps.append(_rung(lvl, "R-mult"))

    out["tps"] = tps
    if tps:
        out["rr1"] = tps[0]["r"]  # ranking still keys on the first target
    return out


# ---- reads -------------------------------------------------------------

def _tp_line(tps: list) -> str:
    """Render TP1/TP2/TP3 with R-multiple and basis."""
    parts = []
    for i, tp in enumerate(tps, 1):
        star = "*" if tp["basis"] == "R-mult" else ""
        parts.append(f"TP{i} ${_fmt(tp['level'])} ({tp['r']}R{star})")
    tail = "  _(*=R-multiple, no structural level that far)_" if any(
        tp["basis"] == "R-mult" for tp in tps) else ""
    return "  - " + " · ".join(parts) + tail


def template_read(a: dict) -> str:
    """Deterministic, grounded markdown read (free, instant; alert + fallback)."""
    L = []
    L.append(f"**{a['inst_id']}** — ${_fmt(a['last'])}  ({a.get('chg_24h_pct'):+}% 24h)"
             if a.get("chg_24h_pct") is not None else f"**{a['inst_id']}** — ${_fmt(a['last'])}")
    bits = []
    if a.get("off_high_pct") is not None:
        bits.append(f"{a['off_high_pct']:+}% off 24h high ${_fmt(a['high24h'])}")
    if a.get("above_low_pct") is not None:
        bits.append(f"{a['above_low_pct']:+}% above 24h low ${_fmt(a['low24h'])}")
    if bits:
        L.append(" · ".join(bits))
    L.append(f"Structure: **{a.get('phase','?')}**, {a.get('micro_pos','?')}.")
    if a.get("peak_retrace_pct") is not None:
        L.append(f"- {a['peak_retrace_pct']:+}% from the recent 1H peak ${_fmt(a.get('peak_1h'))}"
                 + (f" (set {a.get('peak_at_utc','')} UTC)" if a.get("peak_at_utc") else ""))
    if a.get("range_lo") and a.get("range_hi"):
        L.append(f"- working range ${_fmt(a['range_lo'])}–${_fmt(a['range_hi'])}"
                 + (f", last 15m vol {a['last_vol_x']}× avg" if a.get("last_vol_x") is not None else ""))
    if a.get("ma20_1h"):
        side = "above" if (a.get("vs_ma_pct") or 0) >= 0 else "below"
        L.append(f"- price {side} the 1H MA(20) ${_fmt(a['ma20_1h'])} ({a.get('vs_ma_pct'):+}%)")
    if a.get("funding_pct") is not None:
        L.append(f"- funding {a['funding_pct']:+}% ({a['funding_side']})")

    s = a.get("short")
    if s and s.get("tps"):
        L.append(f"**Short setup:** enter ${_fmt(s['entry'])}, stop ${_fmt(s['stop'])} "
                 f"(risk {s.get('risk_pct')}%)")
        L.append(_tp_line(s["tps"]))
        L.append(f"  - invalidation: {a.get('invalidation_short')}")
    lg = a.get("long")
    if lg and lg.get("tps"):
        L.append(f"**Long setup:** enter ${_fmt(lg['entry'])}, stop ${_fmt(lg['stop'])} "
                 f"(risk {lg.get('risk_pct')}%)")
        L.append(_tp_line(lg["tps"]))
        L.append(f"  - invalidation: {a.get('invalidation_long')}")

    L.append("_Caveats: " + "; ".join(a.get("caveats", [])) + "._")
    return "\n\n".join(L)


_SYSTEM = """You are a derivatives desk analyst writing a tight tactical read on one crypto perpetual for an experienced trader. You are given a JSON block of MEASURED structure (price, 24h range, 1H peak/retrace, moving average, local range, volume, funding, and computed long/short defined-risk setups).

Rules:
- Use ONLY numbers present in the JSON. Never invent a price, level, or metric. Describe prices as the measured value.
- Frame as opportunity discovery: give BOTH the long and short case with their explicit invalidation levels. Never issue a single prescriptive "do this" instruction.
- You have NO order-book depth, open interest, or IV — say so if it matters. This is a low-float perp on leverage; flag squeeze/liquidation risk.
- Each setup carries a 3-rung take-profit ladder (tps: TP1/TP2/TP3) — quote all three with their R-multiples (the `r` field). Rungs marked basis "R-mult" are R-multiple extensions (no structural level that far), not measured S/R — say so. Rungs marked "structure" are real levels.
- Be concise and concrete (~200 words). Lead with the structure in one line, then the key levels, then the cleaner of the two setups with its full TP ladder and what would flip it. End with the single most important thing to watch.
- No hype, no emoji. Plain, direct."""


def claude_read(a: dict) -> str:
    """Nuanced Claude read grounded in the computed structure; template fallback."""
    import json
    prompt = ("Write the tactical read from this structure JSON:\n\n```json\n"
              + json.dumps(a, sort_keys=True, default=str) + "\n```")
    res = llm.complete(prompt, system=_SYSTEM, model=llm.DEFAULT_MODEL,
                       max_tokens=1600, adaptive_thinking=True)
    if res and res.get("text"):
        return res["text"]
    return template_read(a)


if __name__ == "__main__":
    import io
    import sys
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    inst = sys.argv[1] if len(sys.argv) > 1 else "BEAT-USDT"
    res = analyze(inst)
    if not res:
        print(f"No data for {inst}")
    else:
        print(template_read(res))
