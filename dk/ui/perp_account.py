"""Read-only Blofin account panel for the dashboard.

Shows your live futures **equity**, aggregate **unrealized PnL**, and a table of
**open perp positions** (side, size, entry, mark, uPnL, leverage, liq price) so
you can see how your real money is doing right next to the call-outs.

Strictly read-only — uses dk.brokers.blofin with a Read-permission API key and
never places, modifies, or cancels an order. If no key is configured, the panel
shows a short how-to and nothing else.
"""
from __future__ import annotations
import pandas as pd
import streamlit as st
from dk.brokers.blofin import BlofinBroker


@st.cache_data(ttl=30, show_spinner=False)
def _snapshot() -> dict:
    """Pull account + positions once, cached 30s (refresh button clears it)."""
    b = BlofinBroker()
    if not b.is_configured():
        return {"configured": False}
    try:
        return {
            "configured": True,
            "account": b.fetch_futures_account(),
            "positions": b.fetch_perp_positions(),
            "error": None,
        }
    except Exception as e:
        return {"configured": True, "account": None, "positions": [], "error": str(e)}


def _fmt(v, dp: int = 4) -> str:
    return f"{v:,.{dp}f}" if isinstance(v, (int, float)) else "—"


def render() -> None:
    """Render the account panel into the current container."""
    st.subheader("💼 My Blofin account (read-only)")

    snap = _snapshot()
    if not snap.get("configured"):
        st.info("Add a **read-only** Blofin API key to see your live equity and open "
                "positions here.\n\n" + BlofinBroker().setup_hint())
        return

    cols = st.columns([1, 1, 1, 1])
    if cols[3].button("↻ Refresh", key="blofin_acct_refresh", use_container_width=True):
        _snapshot.clear()
        st.rerun()

    if snap.get("error"):
        st.warning(f"Couldn't read the Blofin account: {snap['error']}\n\n"
                   "Check that the key is **Read**-enabled and the API Key / Secret / "
                   "Passphrase are correct (and not IP-restricted to a different host).")
        return

    acct = snap.get("account") or {}
    positions = snap.get("positions") or []
    total_upnl = sum(p["upnl"] for p in positions if p.get("upnl") is not None)
    equity = acct.get("total_equity")

    cols[0].metric("Equity (USDT)", _fmt(equity, 2))
    cols[1].metric("Open positions", len(positions))
    cols[2].metric("Unrealized PnL",
                   f"{total_upnl:+,.2f}" if positions else "—",
                   delta=f"{total_upnl:+,.2f}" if positions else None)

    if not positions:
        st.caption("No open perp positions right now. Equity above is your futures "
                   "account balance. Discovery, not instructions — the panel is read-only.")
        return

    df = pd.DataFrame([{
        "Pair": p["inst_id"],
        "Side": "🟢 Long" if p["side"] == "long" else "🔴 Short",
        "Size": _fmt(p["size"], 4),
        "Entry": _fmt(p["avg_price"]),
        "Mark": _fmt(p["mark_price"]),
        "uPnL ($)": None if p["upnl"] is None else round(p["upnl"], 2),
        "uPnL (%)": None if p["upnl_pct"] is None else p["upnl_pct"],
        "Lev": "—" if p["leverage"] is None else f"{p['leverage']:g}x",
        "Liq": _fmt(p["liq_price"]),
        "Mode": p.get("margin_mode") or "—",
    } for p in positions])

    st.dataframe(
        df, use_container_width=True, hide_index=True,
        column_config={
            "uPnL ($)": st.column_config.NumberColumn(format="%+.2f"),
            "uPnL (%)": st.column_config.NumberColumn(format="%+.2f%%"),
        },
    )
    st.caption("Live from Blofin (read-only key). Entry = average fill, Mark = current "
               "mark price, Liq = liquidation price. The app never trades — discovery only.")
