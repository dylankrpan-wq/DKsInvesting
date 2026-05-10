"""Coinbase Advanced Trade adapter (READ-ONLY).

Uses the official `coinbase-advanced-py` SDK with CDP API keys.
Credentials in secrets.env:
  COINBASE_API_KEY_NAME=organizations/{org_id}/apiKeys/{key_id}
  COINBASE_PRIVATE_KEY=-----BEGIN EC PRIVATE KEY-----\n...\n-----END EC PRIVATE KEY-----\n

Generate at https://www.coinbase.com/cloud/api/cdp with 'view' permission only.
"""
from __future__ import annotations
from dk.config import get_key
from dk.brokers.base import Broker, Position


class CoinbaseBroker(Broker):
    name = "coinbase"

    def is_configured(self) -> bool:
        return bool(get_key("COINBASE_API_KEY_NAME") and get_key("COINBASE_PRIVATE_KEY"))

    def setup_hint(self) -> str:
        return ("Generate a CDP API key at https://www.coinbase.com/cloud/api/cdp with "
                "view-only permission. Save COINBASE_API_KEY_NAME and COINBASE_PRIVATE_KEY "
                "in config/secrets.env (private key includes the BEGIN/END lines, "
                "literal `\\n` for newlines).")

    def fetch_positions(self) -> list[Position]:
        try:
            from coinbase.rest import RESTClient
        except ImportError:
            raise RuntimeError("Run: uv add coinbase-advanced-py")
        api_key = get_key("COINBASE_API_KEY_NAME")
        api_secret = get_key("COINBASE_PRIVATE_KEY")
        # SDK expects literal newlines, not '\n'
        if api_secret and "\\n" in api_secret:
            api_secret = api_secret.replace("\\n", "\n")
        client = RESTClient(api_key=api_key, api_secret=api_secret)

        out: list[Position] = []
        accounts = client.get_accounts(limit=250)
        for acc in (accounts.accounts or []):
            try:
                bal = float(acc.available_balance.value or 0)
            except Exception:
                bal = 0.0
            if bal <= 0:
                continue
            currency = acc.currency or "USD"
            symbol = currency
            asset_type = "cash" if currency in {"USD", "USDC", "USDT", "EUR", "GBP"} else "crypto"

            # Get spot price for non-cash crypto holdings
            market_price = None
            market_value = bal
            if asset_type == "crypto":
                try:
                    p = client.get_product(f"{currency}-USD")
                    market_price = float(p.price)
                    market_value = bal * market_price
                except Exception:
                    market_price = None
                    market_value = None

            out.append(Position(
                broker=self.name,
                account_id=acc.uuid,
                symbol=symbol,
                asset_type=asset_type,
                quantity=bal,
                avg_cost=None,                  # Coinbase doesn't expose cost basis via this endpoint
                market_price=market_price,
                market_value=market_value,
                unrealized_pnl=None,
                currency="USD",
            ))
        return out
