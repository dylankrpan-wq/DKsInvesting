"""Robinhood adapter (READ-ONLY) via the unofficial `robin_stocks` library.

WARNING: Robinhood does not offer a public API. This uses a community-reverse-engineered
endpoint that may break or violate ToS. Use at your own risk on a personal account.

Credentials in secrets.env:
  ROBINHOOD_USERNAME=
  ROBINHOOD_PASSWORD=
  ROBINHOOD_MFA_CODE=     # optional; if set, used for non-interactive 2FA setup

If your account has SMS 2FA enabled, the first login may require interactive entry —
in that case run `uv run python -m dk.brokers.robinhood` once from a terminal.
"""
from __future__ import annotations
from dk.config import get_key
from dk.brokers.base import Broker, Position


class RobinhoodBroker(Broker):
    name = "robinhood"

    def is_configured(self) -> bool:
        return bool(get_key("ROBINHOOD_USERNAME") and get_key("ROBINHOOD_PASSWORD"))

    def setup_hint(self) -> str:
        return ("Set ROBINHOOD_USERNAME and ROBINHOOD_PASSWORD in config/secrets.env. "
                "Run `uv add robin-stocks` and `uv add pyotp` if you have TOTP 2FA. "
                "Note: Robinhood's API is unofficial and may break.")

    def fetch_positions(self) -> list[Position]:
        try:
            import robin_stocks.robinhood as rh
        except ImportError:
            raise RuntimeError("Run: uv add robin-stocks")
        user = get_key("ROBINHOOD_USERNAME")
        pwd = get_key("ROBINHOOD_PASSWORD")
        mfa = get_key("ROBINHOOD_MFA_CODE")

        login_kwargs = {"username": user, "password": pwd, "expiresIn": 86400, "store_session": True}
        if mfa:
            try:
                import pyotp
                login_kwargs["mfa_code"] = pyotp.TOTP(mfa).now()
            except ImportError:
                pass
        rh.login(**login_kwargs)

        out: list[Position] = []
        # Equity holdings
        holdings = rh.build_holdings() or {}
        for sym, h in holdings.items():
            qty = float(h.get("quantity") or 0)
            if qty <= 0:
                continue
            avg = float(h.get("average_buy_price") or 0) or None
            price = float(h.get("price") or 0) or None
            mv = qty * price if price else None
            pnl = (price - avg) * qty if (price and avg) else None
            out.append(Position(
                broker=self.name, account_id=None, symbol=sym, asset_type="equity",
                quantity=qty, avg_cost=avg, market_price=price,
                market_value=mv, unrealized_pnl=pnl, currency="USD",
            ))

        # Crypto holdings
        try:
            crypto = rh.crypto.get_crypto_positions() or []
            for c in crypto:
                qty = float((c.get("quantity") or 0))
                if qty <= 0:
                    continue
                sym = (c.get("currency") or {}).get("code", "?")
                avg = float(c.get("cost_bases", [{}])[0].get("direct_cost_basis", 0)) / qty if qty else None
                quote = rh.crypto.get_crypto_quote(sym)
                price = float(quote.get("mark_price")) if quote else None
                mv = qty * price if price else None
                pnl = (price - avg) * qty if (price and avg) else None
                out.append(Position(
                    broker=self.name, account_id=None, symbol=sym, asset_type="crypto",
                    quantity=qty, avg_cost=avg, market_price=price,
                    market_value=mv, unrealized_pnl=pnl, currency="USD",
                ))
        except Exception as e:
            print(f"[robinhood] crypto fetch skipped: {e}")
        return out


if __name__ == "__main__":
    # Manual interactive login helper (handles SMS 2FA prompts)
    b = RobinhoodBroker()
    if not b.is_configured():
        print("Not configured."); raise SystemExit(1)
    pos = b.fetch_positions()
    for p in pos:
        print(p)
