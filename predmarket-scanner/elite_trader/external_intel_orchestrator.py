"""Scheduled CoinGecko + CoinMarketCap cold polls — never on hot path."""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from elite_trader.coingecko_client import CoinGeckoClient
from elite_trader.coinmarketcap_client import CoinMarketCapClient

log = logging.getLogger("elite.external_intel")

_MAJORS = [
    "BTC", "ETH", "BNB", "SOL", "XRP", "DOGE", "ADA", "AVAX", "DOT", "LINK",
    "MATIC", "LTC", "UNI", "ATOM", "NEAR", "APT", "ARB", "OP", "SUI", "PEPE",
]


class ExternalIntelOrchestrator:
    """Staggered CG/CMC polls with semaphore (max 2 concurrent HTTP)."""

    def __init__(self) -> None:
        self.cg = CoinGeckoClient()
        self.cmc = CoinMarketCapClient()
        self._sem = asyncio.Semaphore(2)
        self._stop = asyncio.Event()
        self._phase = 0
        self.last_cycle_ms = 0

    async def stop(self) -> None:
        self._stop.set()

    async def run_forever(self) -> None:
        while not self._stop.is_set():
            try:
                await self._cycle()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("external intel cycle: %s", exc)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=30.0)
                break
            except asyncio.TimeoutError:
                pass

    async def _cycle(self) -> None:
        self._phase = (self._phase + 1) % 4
        self.last_cycle_ms = int(time.time() * 1000)
        if self._phase == 0:
            await self._with_sem(self._cg_majors())
        elif self._phase == 1:
            await self._with_sem(self._cmc_quotes())
        elif self._phase == 2:
            await self._with_sem(self._cmc_listings_global())
        else:
            await self._with_sem(self._cg_markets())
        self._push_to_hub()

    async def _with_sem(self, coro) -> None:
        async with self._sem:
            await coro

    async def _cg_majors(self) -> None:
        await self.cg.fetch_simple_prices(_MAJORS)

    async def _cg_markets(self) -> None:
        await self.cg.fetch_markets()

    async def _cmc_quotes(self) -> None:
        await self.cmc.fetch_quotes(_MAJORS)

    async def _cmc_listings_global(self) -> None:
        await self.cmc.fetch_listings()
        await self.cmc.fetch_global_metrics()

    def _push_to_hub(self) -> None:
        try:
            from elite_trader.market_intelligence_hub import get_hub

            hub = get_hub()
            hub.refresh_coingecko(self.cg)
            hub.refresh_coinmarketcap(self.cmc)
        except Exception as exc:
            log.debug("hub push: %s", exc)

    def status(self) -> dict[str, Any]:
        return {
            "phase": self._phase,
            "last_cycle_ms": self.last_cycle_ms,
            "coingecko": self.cg.status(),
            "coinmarketcap": self.cmc.status(),
        }
