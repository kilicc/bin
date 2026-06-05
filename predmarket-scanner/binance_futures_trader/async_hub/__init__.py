"""Asyncio Binance Futures market + user data hub."""
from __future__ import annotations

import os

from binance_futures_trader.async_hub.orchestrator import (
    get_orchestrator,
    hub_enabled,
    start_hub,
    stop_hub,
)
from binance_futures_trader.async_hub.price_cache import HotPriceCache

__all__ = [
    "HotPriceCache",
    "get_orchestrator",
    "hub_enabled",
    "start_hub",
    "stop_hub",
]


def is_async_hub_enabled() -> bool:
    return hub_enabled()
