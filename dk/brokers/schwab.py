"""Schwab adapter (scaffold).

Schwab provides an OFFICIAL API but it requires:
  1. Register as developer at https://developer.schwab.com
  2. Create an app with 'Read-only' scope; wait for approval (~1-3 business days)
  3. OAuth2 flow: capture authorization code, exchange for access + refresh tokens
  4. Refresh-token lifecycle (7-day expiry; needs re-auth dance)

Once approved, set in secrets.env:
  SCHWAB_APP_KEY=
  SCHWAB_APP_SECRET=
  SCHWAB_REFRESH_TOKEN=     # obtained from one-time OAuth flow

Recommended Python lib: `schwab-py` (third-party but mature)

This adapter is currently a stub — fill in once you've completed the dev-portal
registration. For now, it always reports unconfigured.
"""
from __future__ import annotations
from dk.config import get_key
from dk.brokers.base import Broker, Position


class SchwabBroker(Broker):
    name = "schwab"

    def is_configured(self) -> bool:
        return all([get_key("SCHWAB_APP_KEY"), get_key("SCHWAB_APP_SECRET"),
                    get_key("SCHWAB_REFRESH_TOKEN")])

    def setup_hint(self) -> str:
        return ("Register an app at https://developer.schwab.com (1-3 day approval). "
                "Read-only scope. Run the OAuth flow once to obtain a refresh token. "
                "Then `uv add schwab-py` and complete the fetch_positions implementation.")

    def fetch_positions(self) -> list[Position]:
        # TODO: implement once dev-portal app is approved.
        # from schwab.auth import client_from_token_file
        # client = client_from_token_file(...)
        # accounts = client.get_account_numbers().json()
        # positions = client.get_account(account_hash, fields=["positions"]).json()
        raise NotImplementedError(
            "Schwab adapter not yet implemented — dev portal registration required first. "
            "See dk/brokers/schwab.py for setup steps."
        )
