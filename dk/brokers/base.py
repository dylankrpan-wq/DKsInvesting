"""Broker adapter contract."""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class Position:
    broker: str
    account_id: str | None
    symbol: str
    asset_type: str       # 'equity' | 'crypto' | 'cash'
    quantity: float
    avg_cost: float | None
    market_price: float | None
    market_value: float | None
    unrealized_pnl: float | None
    currency: str = "USD"

    def to_row(self) -> dict:
        return self.__dict__.copy()


class Broker(ABC):
    name: str = "base"

    @abstractmethod
    def is_configured(self) -> bool:
        """Return True if credentials are present in env."""
        ...

    @abstractmethod
    def fetch_positions(self) -> list[Position]:
        """Return current positions across all sub-accounts. READ-ONLY."""
        ...

    def setup_hint(self) -> str:
        """Help string shown when not configured."""
        return f"Configure {self.name} by adding credentials to config/secrets.env"
