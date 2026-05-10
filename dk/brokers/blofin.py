"""Blofin adapter (READ-ONLY).

Blofin's API uses an HMAC-signed REST request:
  GET /api/v1/asset/balances    -> spot/funding balances
  GET /api/v1/account/balance   -> futures account

Credentials in secrets.env:
  BLOFIN_API_KEY=
  BLOFIN_API_SECRET=
  BLOFIN_API_PASSPHRASE=

Generate at https://blofin.com (account → API) with 'read' permission only.
Docs: https://docs.blofin.com/
"""
from __future__ import annotations
import base64
import hashlib
import hmac
import json
import time
import requests
from dk.config import get_key
from dk.brokers.base import Broker, Position

BASE = "https://openapi.blofin.com"


class BlofinBroker(Broker):
    name = "blofin"

    def is_configured(self) -> bool:
        return all([get_key("BLOFIN_API_KEY"), get_key("BLOFIN_API_SECRET"),
                    get_key("BLOFIN_API_PASSPHRASE")])

    def setup_hint(self) -> str:
        return ("Generate a Blofin API key (read-only) at https://blofin.com → API Management. "
                "Set BLOFIN_API_KEY, BLOFIN_API_SECRET, BLOFIN_API_PASSPHRASE in secrets.env.")

    def _sign(self, method: str, path: str, body: str = "") -> dict:
        ts = str(int(time.time() * 1000))
        nonce = ts
        # Blofin signature: HMAC-SHA256 of (path + method + ts + nonce + body) base64-encoded
        prehash = path + method + ts + nonce + body
        sec = get_key("BLOFIN_API_SECRET").encode()
        sig = base64.b64encode(hmac.new(sec, prehash.encode(), hashlib.sha256).digest()).decode()
        return {
            "ACCESS-KEY": get_key("BLOFIN_API_KEY"),
            "ACCESS-SIGN": sig,
            "ACCESS-TIMESTAMP": ts,
            "ACCESS-NONCE": nonce,
            "ACCESS-PASSPHRASE": get_key("BLOFIN_API_PASSPHRASE"),
            "Content-Type": "application/json",
        }

    def fetch_positions(self) -> list[Position]:
        path = "/api/v1/asset/balances"
        headers = self._sign("GET", path)
        r = requests.get(BASE + path, headers=headers, timeout=15)
        if r.status_code != 200:
            raise RuntimeError(f"blofin HTTP {r.status_code}: {r.text[:200]}")
        data = r.json()
        if data.get("code") not in ("0", 0):
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
