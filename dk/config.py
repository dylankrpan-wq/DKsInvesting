from __future__ import annotations
import os
from pathlib import Path
import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"

# DATA_DIR is overridable via DK_DATA_DIR so a host (e.g. Railway) can point it
# at a persistent volume mount like /data. Defaults to ./data for local use.
DATA_DIR = Path(os.getenv("DK_DATA_DIR", str(ROOT / "data")))
DATA_DIR.mkdir(parents=True, exist_ok=True)

load_dotenv(CONFIG_DIR / "secrets.env")

DB_PATH = DATA_DIR / "dk.db"


_USER_WATCHLIST = CONFIG_DIR / "watchlist_user.yaml"


def load_watchlist() -> dict:
    """Load main watchlist.yaml, then merge user additions from watchlist_user.yaml."""
    with open(CONFIG_DIR / "watchlist.yaml", "r", encoding="utf-8") as f:
        wl = yaml.safe_load(f) or {}
    if _USER_WATCHLIST.exists():
        with open(_USER_WATCHLIST, "r", encoding="utf-8") as f:
            user = yaml.safe_load(f) or {}
        for key in ("equities", "etfs", "crypto"):
            base = wl.get(key) or []
            extras = user.get(key) or []
            existing = {(e.get("symbol") or "").upper() for e in base}
            for e in extras:
                if (e.get("symbol") or "").upper() not in existing:
                    base.append(e)
            wl[key] = base
    return wl


def _load_user_additions() -> dict:
    if not _USER_WATCHLIST.exists():
        return {"equities": [], "etfs": [], "crypto": []}
    with open(_USER_WATCHLIST, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    for k in ("equities", "etfs", "crypto"):
        data.setdefault(k, [])
    return data


def _save_user_additions(data: dict) -> None:
    header = (
        "# DK Investing — user-added watchlist entries.\n"
        "# Edit via the dashboard's Watchlist tab, or hand-edit and save.\n"
        "# Anything here is MERGED on top of config/watchlist.yaml at load time.\n\n"
    )
    with open(_USER_WATCHLIST, "w", encoding="utf-8") as f:
        f.write(header)
        yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)


def add_to_watchlist(symbol: str, name: str, kind: str = "equities",
                     region: str = "US", coingecko_id: str | None = None) -> bool:
    """Append a ticker to the user-additions file. Returns True if added, False if duplicate."""
    symbol = (symbol or "").strip().upper()
    if not symbol:
        return False
    data = _load_user_additions()
    bucket = data.setdefault(kind, [])
    if any((e.get("symbol") or "").upper() == symbol for e in bucket):
        return False
    if kind == "crypto":
        bucket.append({"symbol": symbol, "coingecko_id": coingecko_id or symbol.lower()})
    else:
        bucket.append({"symbol": symbol, "name": name or symbol, "region": region})
    _save_user_additions(data)
    return True


def remove_from_watchlist(symbol: str) -> bool:
    """Remove a user-added ticker. Cannot remove entries from base watchlist.yaml."""
    symbol = (symbol or "").strip().upper()
    data = _load_user_additions()
    removed = False
    for kind in ("equities", "etfs", "crypto"):
        before = len(data.get(kind, []))
        data[kind] = [e for e in data.get(kind, []) if (e.get("symbol") or "").upper() != symbol]
        if len(data[kind]) < before:
            removed = True
    if removed:
        _save_user_additions(data)
    return removed


def is_user_added(symbol: str) -> bool:
    symbol = (symbol or "").strip().upper()
    data = _load_user_additions()
    for kind in ("equities", "etfs", "crypto"):
        if any((e.get("symbol") or "").upper() == symbol for e in data.get(kind, [])):
            return True
    return False


def equity_symbols() -> list[str]:
    wl = load_watchlist()
    return [e["symbol"] for e in (wl.get("equities") or []) + (wl.get("etfs") or [])]


def crypto_ids() -> list[tuple[str, str]]:
    wl = load_watchlist()
    return [(c["symbol"], c["coingecko_id"]) for c in (wl.get("crypto") or [])]


def get_key(name: str) -> str | None:
    """Read a secret. Tries env var first, then Streamlit's st.secrets if available.

    This lets the same code work locally (uses config/secrets.env via dotenv)
    AND on Streamlit Community Cloud (uses Settings → Secrets in the dashboard).
    """
    v = os.getenv(name)
    if v:
        return v
    # Fall back to streamlit secrets if available (cloud deployment)
    try:
        import streamlit as st
        if name in st.secrets:
            val = st.secrets[name]
            return str(val) if val else None
    except Exception:
        pass
    return None
