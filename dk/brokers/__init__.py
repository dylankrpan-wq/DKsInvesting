"""Broker adapter registry.

All adapters are READ-ONLY. No trade execution paths.
Each adapter is opt-in: missing credentials → silent skip.
"""
from __future__ import annotations
from dk.brokers.base import Broker
from dk.brokers.coinbase import CoinbaseBroker
from dk.brokers.robinhood import RobinhoodBroker
from dk.brokers.blofin import BlofinBroker
from dk.brokers.schwab import SchwabBroker

ALL_BROKERS: list[type[Broker]] = [
    CoinbaseBroker, RobinhoodBroker, BlofinBroker, SchwabBroker,
]


def all_configured() -> list[Broker]:
    """Instantiate every broker that has credentials available."""
    out: list[Broker] = []
    for cls in ALL_BROKERS:
        try:
            inst = cls()
            if inst.is_configured():
                out.append(inst)
        except Exception as e:
            print(f"[brokers] {cls.__name__} init error: {e}")
    return out
