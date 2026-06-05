"""Asyncio market streams: !bookTicker + !markPrice@arr@1s (ayrı WS)."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Any

import websockets
from websockets.exceptions import ConnectionClosed

from binance_futures_trader.async_hub.price_cache import HotPriceCache
from binance_futures_trader.async_hub.ws_urls import DEMO_WS_SECONDARY, ws_market_base

log = logging.getLogger("bn.async_hub.market")


def _hub_mark_lite() -> bool:
    """BERSERK2-only: !markPrice@arr (700+ coin/sn) kapalı — RAM."""
    return os.getenv("BN_FUT_HUB_LITE", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _coin_from_symbol(sym: str) -> str:
    s = str(sym or "").upper()
    if s.endswith("USDT"):
        return s[:-4]
    return s


class MarketStream:
    """bookTicker + markPrice — iki paralel WS (combined global stream güvenilir değil)."""

    RECONNECT_BASE = 1.0
    RECONNECT_MAX = 30.0

    def __init__(self, cache: HotPriceCache) -> None:
        self.cache = cache
        self._tasks: list[asyncio.Task] = []
        self._stop = asyncio.Event()
        self.book_connected = False
        self.mark_connected = False
        self.reconnects = 0
        self.last_error: str | None = None
        self._book_url: str | None = None
        self._mark_url: str | None = None

    async def start(self) -> None:
        if self._tasks:
            return
        self._stop.clear()
        self._tasks = [asyncio.create_task(self._run_book(), name="bn-book-stream")]
        if not _hub_mark_lite():
            self._tasks.append(
                asyncio.create_task(self._run_mark(), name="bn-mark-stream")
            )

    async def stop(self) -> None:
        self._stop.set()
        for t in self._tasks:
            t.cancel()
        for t in self._tasks:
            try:
                await t
            except asyncio.CancelledError:
                pass
        self._tasks.clear()
        self.book_connected = False
        self.mark_connected = False

    async def _connect_loop(self, path: str, *, label: str) -> None:
        backoff = self.RECONNECT_BASE
        bases = [ws_market_base(), DEMO_WS_SECONDARY]
        idx = 0
        while not self._stop.is_set():
            base = bases[idx % len(bases)]
            url = f"{base}{path}"
            if label == "book":
                self._book_url = url
            else:
                self._mark_url = url
            try:
                max_sz = 512 * 1024 if _hub_mark_lite() else 8 * 1024 * 1024
                async with websockets.connect(
                    url,
                    ping_interval=20,
                    ping_timeout=20,
                    close_timeout=5,
                    max_size=max_sz,
                ) as ws:
                    if label == "book":
                        self.book_connected = True
                    else:
                        self.mark_connected = True
                    backoff = self.RECONNECT_BASE
                    log.info("%s WS connected %s", label, base)
                    async for raw in ws:
                        if self._stop.is_set():
                            break
                        if label == "book":
                            self._handle_book(raw)
                        else:
                            self._handle_mark(raw)
            except asyncio.CancelledError:
                raise
            except ConnectionClosed as exc:
                if label == "book":
                    self.book_connected = False
                else:
                    self.mark_connected = False
                self.last_error = str(exc)[:120]
            except Exception as exc:
                if label == "book":
                    self.book_connected = False
                else:
                    self.mark_connected = False
                self.last_error = str(exc)[:120]
                log.warning("%s WS error: %s", label, self.last_error)
            if self._stop.is_set():
                break
            self.reconnects += 1
            idx += 1
            await asyncio.sleep(min(backoff, self.RECONNECT_MAX))
            backoff = min(backoff * 1.5, self.RECONNECT_MAX)

    async def _run_book(self) -> None:
        await self._connect_loop("/ws/!bookTicker", label="book")

    async def _run_mark(self) -> None:
        await self._connect_loop("/ws/!markPrice@arr@1s", label="mark")

    def _handle_book(self, raw: str | bytes) -> None:
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            return
        if isinstance(msg, dict) and msg.get("stream"):
            msg = msg.get("data") or msg
        if not isinstance(msg, dict):
            return
        sym = str(msg.get("s") or "")
        coin = _coin_from_symbol(sym)
        bid = float(msg.get("b") or 0)
        ask = float(msg.get("a") or 0)
        ts = int(msg.get("E") or msg.get("T") or time.time() * 1000)
        self.cache.update_mid(coin, bid, ask, ts)

    def _handle_mark(self, raw: str | bytes) -> None:
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            return
        rows: list[Any]
        if isinstance(msg, list):
            rows = msg
        elif isinstance(msg, dict):
            data = msg.get("data")
            if isinstance(data, list):
                rows = data
            elif data and isinstance(data, dict):
                rows = [data]
            elif msg.get("e") == "markPriceUpdate":
                rows = [msg]
            else:
                return
        else:
            return
        for row in rows:
            if not isinstance(row, dict):
                continue
            sym = str(row.get("s") or "")
            coin = _coin_from_symbol(sym)
            px = float(row.get("p") or row.get("markPrice") or 0)
            ts = int(row.get("E") or row.get("T") or time.time() * 1000)
            self.cache.update_mark(coin, px, ts)

    def status(self) -> dict[str, Any]:
        st = self.cache.status()
        st.update(
            {
                "connected": self.book_connected or self.mark_connected,
                "book_connected": self.book_connected,
                "mark_connected": self.mark_connected,
                "reconnects": self.reconnects,
                "book_url": self._book_url,
                "mark_url": self._mark_url,
                "ws_url": self._book_url,
                "last_error": self.last_error,
            }
        )
        return st
