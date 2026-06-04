"""Supervisor for asyncio Binance hub + cold-path tasks."""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any, Callable

from binance_futures_trader.async_hub.core_stream import CoreSymbolStream
from binance_futures_trader.async_hub.market_stream import MarketStream
from binance_futures_trader.async_hub.price_cache import HotPriceCache
from binance_futures_trader.async_hub.user_data_stream import UserDataStream

log = logging.getLogger("bn.async_hub.orchestrator")

_orchestrator: "DataOrchestrator | None" = None


def hub_enabled() -> bool:
    return os.getenv("BN_FUT_ASYNC_HUB", "").strip().lower() in ("1", "true", "yes", "on")


class CircuitBreaker:
    def __init__(self, *, max_failures: int = 3, pause_sec: float = 60.0) -> None:
        self.max_failures = max_failures
        self.pause_sec = pause_sec
        self.failures = 0
        self.paused_until = 0.0

    def record_success(self) -> None:
        self.failures = 0
        self.paused_until = 0.0

    def record_failure(self) -> None:
        self.failures += 1
        if self.failures >= self.max_failures:
            self.paused_until = time.time() + self.pause_sec
            self.failures = 0

    def open(self) -> bool:
        return time.time() < self.paused_until


class DataOrchestrator:
    """Single asyncio supervisor — market WS, UDS, reconcile, external intel."""

    RECONCILE_SEC = 60.0

    def __init__(
        self,
        *,
        api_key: str = "",
        on_wallet: Callable[[dict[str, Any]], None] | None = None,
        on_positions: Callable[[list[dict[str, Any]]], None] | None = None,
        reconcile_fn: Callable[[], None] | None = None,
    ) -> None:
        self.cache = HotPriceCache()
        self.market = MarketStream(self.cache)
        self.uds = UserDataStream(
            api_key=api_key,
            on_wallet=on_wallet,
            on_positions=on_positions,
        )
        self.core = CoreSymbolStream()
        self.on_wallet = on_wallet
        self.on_positions = on_positions
        self.reconcile_fn = reconcile_fn
        self._tasks: list[asyncio.Task] = []
        self._started = False
        self._reconcile_breaker = CircuitBreaker()
        self._intel_breaker = CircuitBreaker()
        self._external_intel: Any = None

    async def start(self, *, core_symbols: list[str] | None = None) -> None:
        if self._started:
            return
        self._started = True
        await self.market.start()
        if self.uds.api_key:
            await self.uds.start()
        if core_symbols:
            await self.core.start(core_symbols)
        self._tasks.append(asyncio.create_task(self._reconcile_loop(), name="hub-reconcile"))
        self._tasks.append(asyncio.create_task(self._watchdog_loop(), name="hub-watchdog"))
        import os

        if os.getenv("ELITE_EXTERNAL_INTEL", "1").strip().lower() in (
            "1",
            "true",
            "yes",
        ):
            try:
                from elite_trader.external_intel_orchestrator import (
                    ExternalIntelOrchestrator,
                )

                self._external_intel = ExternalIntelOrchestrator()
                self._tasks.append(
                    asyncio.create_task(
                        self._external_intel.run_forever(), name="external-intel"
                    )
                )
            except Exception as exc:
                log.warning("external intel unavailable: %s", exc)

    async def stop(self) -> None:
        self._started = False
        for t in self._tasks:
            t.cancel()
        for t in self._tasks:
            try:
                await t
            except asyncio.CancelledError:
                pass
        self._tasks.clear()
        if self._external_intel:
            await self._external_intel.stop()
        await self.core.stop()
        await self.uds.stop()
        await self.market.stop()

    async def _reconcile_loop(self) -> None:
        while True:
            await asyncio.sleep(self.RECONCILE_SEC)
            if self._reconcile_breaker.open():
                continue
            if not self.reconcile_fn:
                continue
            try:
                await asyncio.wait_for(
                    asyncio.to_thread(self.reconcile_fn),
                    timeout=8.0,
                )
                self._reconcile_breaker.record_success()
            except Exception as exc:
                log.warning("reconcile failed: %s", exc)
                self._reconcile_breaker.record_failure()

    async def _watchdog_loop(self) -> None:
        while True:
            await asyncio.sleep(5.0)
            st = self.cache.status()
            lag = st.get("lag_ms")
            if lag is not None and lag > 5000 and self.market.connected:
                log.warning("market cache stale %sms — reconnecting", lag)
                await self.market.stop()
                await self.market.start()

    def get_prices_for_coins(
        self, coins: list[str], *, max_age_ms: float = 900
    ) -> dict[str, float]:
        return self.cache.get_prices_for_coins(coins, max_age_ms=max_age_ms)

    def get_all_mids_if_fresh(self, *, max_age_ms: float = 900) -> dict[str, dict[str, float | int]]:
        return self.cache.get_all_mids_snapshot(max_age_ms=max_age_ms)

    def get_all_marks_if_fresh(self, *, max_recv_age_sec: float = 90) -> dict[str, float]:
        return self.cache.get_all_marks_if_fresh(max_recv_age_sec=max_recv_age_sec)

    def get_all_prices_bulk(self, *, max_recv_age_sec: float = 60) -> dict[str, float]:
        return self.cache.get_all_prices_bulk(max_recv_age_sec=max_recv_age_sec)

    def status(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "enabled": True,
            "market": self.market.status(),
            "uds": self.uds.status(),
            "core": self.core.status(),
            "reconcile_paused": self._reconcile_breaker.open(),
        }
        if self._external_intel:
            out["external_intel"] = self._external_intel.status()
        return out


def get_orchestrator() -> DataOrchestrator | None:
    return _orchestrator


async def start_hub(
    *,
    api_key: str = "",
    on_wallet: Callable[[dict[str, Any]], None] | None = None,
    on_positions: Callable[[list[dict[str, Any]]], None] | None = None,
    reconcile_fn: Callable[[], None] | None = None,
    core_symbols: list[str] | None = None,
) -> DataOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = DataOrchestrator(
            api_key=api_key,
            on_wallet=on_wallet,
            on_positions=on_positions,
            reconcile_fn=reconcile_fn,
        )
    await _orchestrator.start(core_symbols=core_symbols)
    return _orchestrator


async def stop_hub() -> None:
    global _orchestrator
    if _orchestrator:
        await _orchestrator.stop()
        _orchestrator = None
