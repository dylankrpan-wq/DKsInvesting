"""Blofin adapter (READ-ONLY).

Blofin's API uses an HMAC-signed REST request. Endpoints used here:
  GET /api/v1/asset/balances    -> spot/funding wallet balances
  GET /api/v1/trade/account     -> futures account equity (totalEquity, details)
  GET /api/v1/trade/positions   -> open perp positions (size, entry, mark, uPnL…)

Credentials in secrets.env (and Railway → Variables):
  BLOFIN_API_KEY=
  BLOFIN_API_SECRET=
  BLOFIN_API_PASSPHRASE=

Generate at https://blofin.com → API Management with **Read** permission ONLY
(leave Trade / Withdraw / Transfer unchecked). This module never places, modifies,
or cancels orders, and never moves funds. Docs: https://docs.blofin.com/

Signature (per Blofin docs): prehash = requestPath + method + timestamp + nonce + body,
then HMAC-SHA256(secret, prehash) -> HEX string -> base64. ACCESS-SIGN is the base64
of the *hex string*, NOT of the raw digest bytes (a subtle but mandatory detail).
"""
from __future__ import annotations
import base64
import hashlib
import hmac
import time
import uuid
from urllib.parse import urlencode
import requests
from dk.config import get_key
from dk.brokers.base import Broker, Position

BASE = "https://openapi.blofin.com"


def _f(v) -> float | None:
    """Best-effort float; None on empty/garbage (Blofin returns numbers as strings)."""
    try:
        if v in (None, "", "null"):
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _norm_position(row: dict) -> dict | None:
    """Normalize one Blofin position row into a flat display dict. None if flat."""
    try:
        size = float(row.get("positions") or 0)
    except (TypeError, ValueError):
        size = 0.0
    if size == 0:
        return None  # no open exposure
    side = (row.get("positionSide") or "").lower()
    if side not in ("long", "short"):
        side = "long" if size > 0 else "short"  # net mode: sign carries direction
    ratio = _f(row.get("unrealizedPnlRatio"))
    return {
        "inst_id": row.get("instId"),
        "side": side,
        "size": abs(size),
        "avg_price": _f(row.get("averagePrice")),
        "mark_price": _f(row.get("markPrice")),
        "upnl": _f(row.get("unrealizedPnl")),
        "upnl_pct": round(ratio * 100, 2) if ratio is not None else None,
        "leverage": _f(row.get("leverage")),
        "liq_price": _f(row.get("liquidationPrice")),
        "margin": _f(row.get("margin")),
        "margin_mode": row.get("marginMode"),
    }


class BlofinBroker(Broker):
    name = "blofin"

    def is_configured(self) -> bool:
        return all([get_key("BLOFIN_API_KEY"), get_key("BLOFIN_API_SECRET"),
                    get_key("BLOFIN_API_PASSPHRASE")])

    def setup_hint(self) -> str:
        return ("Generate a Blofin API key (Read-only) at https://blofin.com → API Management "
                "— leave Trade/Withdraw/Transfer unchecked. Set BLOFIN_API_KEY, "
                "BLOFIN_API_SECRET, BLOFIN_API_PASSPHRASE in secrets.env (and Railway Variables).")

    def _sign(self, method: str, path: str, body: str = "") -> dict:
        """Build signed headers. `path` MUST include the query string for GET."""
        ts = str(int(time.time() * 1000))
        nonce = str(uuid.uuid4())  # Blofin requires a unique nonce (UUID recommended)
        prehash = path + method + ts + nonce + body
        sec = (get_key("BLOFIN_API_SECRET") or "").encode()
        # HMAC-SHA256 -> hex string -> base64 (NOT base64 of the raw digest).
        hex_sig = hmac.new(sec, prehash.encode(), hashlib.sha256).hexdigest()
        sig = base64.b64encode(hex_sig.encode()).decode()
        return {
            "ACCESS-KEY": get_key("BLOFIN_API_KEY") or "",
            "ACCESS-SIGN": sig,
            "ACCESS-TIMESTAMP": ts,
            "ACCESS-NONCE": nonce,
            "ACCESS-PASSPHRASE": get_key("BLOFIN_API_PASSPHRASE") or "",
            "Content-Type": "application/json",
        }

    def _signed_get(self, path: str, params: dict | None = None, timeout: int = 15):
        """Signed GET. Returns the parsed `data` payload, or raises RuntimeError."""
        query = "?" + urlencode(params) if params else ""
        full = path + query  # the signature must cover the query string too
        headers = self._sign("GET", full)
        r = requests.get(BASE + full, headers=headers, timeout=timeout)
        if r.status_code != 200:
            raise RuntimeError(f"blofin HTTP {r.status_code}: {r.text[:200]}")
        data = r.json()
        if str(data.get("code")) not in ("0",):
            raise RuntimeError(f"blofin API error {data.get('code')}: {data.get('msg', data)}")
        return data.get("data")

    # ---- Read-only account views -------------------------------------------

    def fetch_futures_account(self) -> dict | None:
        """Futures account equity. {total_equity, isolated_equity, details[]}."""
        data = self._signed_get("/api/v1/trade/account")
        if data is None:
            return None
        if isinstance(data, list):
            data = data[0] if data else {}
        return {
            "total_equity": _f(data.get("totalEquity")),
            "isolated_equity": _f(data.get("isolatedEquity")),
            "details": data.get("details") or [],
        }

    def fetch_perp_positions(self) -> list[dict]:
        """Open perp positions, normalized + flat-filtered. Empty list if none."""
        data = self._signed_get("/api/v1/trade/positions") or []
        if isinstance(data, dict):  # be tolerant of either shape
            data = data.get("positions") or [data]
        out = [_norm_position(r) for r in data]
        return [p for p in out if p]

    # ---- Broker contract (spot/funding wallet) -----------------------------

    def fetch_positions(self) -> list[Position]:
        """Wallet balances as Positions (Broker contract). READ-ONLY."""
        path = "/api/v1/asset/balances"
        headers = self._sign("GET", path)
        r = requests.get(BASE + path, headers=headers, timeout=15)
        if r.status_code != 200:
            raise RuntimeError(f"blofin HTTP {r.status_code}: {r.text[:200]}")
        data = r.json()
        if str(data.get("code")) not in ("0",):
            raise RuntimeError(f"blofin API error: {data.get('msg', data)}")

        out: list[Position] = []
        for row in (data.get("data") or []):
            currency = row.get("currency") or row.get("ccy") or "?"
            avail = float(row.get("available") or 0) + float(row.get("frozen") or 0)
            if avail <= 0:
                continue
            asset_type = "cash" if currency in {"USDT", "USDC", "USD"} else "crypto"
            out.append(Position(
                broker=self.name, account_id="spot", symbol=currency, asset_type=asset_type,
                quantity=avail, avg_cost=None, market_price=None,
                market_value=None, unrealized_pnl=None, currency="USD",
            ))
        return out


if __name__ == "__main__":
    # Quick connectivity self-test: `python -m dk.brokers.blofin`
    import sys
    try:  # Windows consoles default to cp1252 and choke on ✅/→ — force UTF-8.
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    except Exception:
        pass
    b = BlofinBroker()
    if not b.is_configured():
        print("Blofin not configured.\n" + b.setup_hint())
        raise SystemExit(1)
    try:
        acct = b.fetch_futures_account() or {}
        print(f"✅ Connected. Futures equity (USDT): {acct.get('total_equity')}")
        positions = b.fetch_perp_positions()
        if not positions:
            print("No open perp positions.")
        for p in positions:
            print(f"  {p['side']:5} {p['inst_id']:14} size={p['size']} "
                  f"entry={p['avg_price']} mark={p['mark_price']} "
                  f"uPnL={p['upnl']} ({p['upnl_pct']}%) {p['leverage']}x liq={p['liq_price']}")
    except Exception as e:
        print(f"❌ Read failed: {e}\n"
              "Check the key is Read-enabled and the Key/Secret/Passphrase are correct.")
        raise SystemExit(1)
