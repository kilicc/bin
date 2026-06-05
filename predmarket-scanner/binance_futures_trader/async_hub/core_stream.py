"""Combined kline + depth streams for tradable core (~50 symbols)."""
from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from typing import Any

import websockets
from websockets.exceptions import ConnectionClosed

from binance_futures_trader.async_hub.ws_urls import ws_market_base

log = logging.getLogger("bn.async_hub.core")


class CoreSymbolStream:
    """Optional depth/kline WS for tradable core — cold enrichment, not hot execution."""

    MAX_SYMBOLS = 50
    RECONNECT_BASE = 2.0
    RECONNECT_MAX = 45.0

    def __init__(self) -> None:
        self._symbols: list[str] = []
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self.connected = False
        self.reconnects = 0
        self.last_error: str | None = None
        self._klines: dict[str, list[float]] = {}
        self._depth: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def set_symbols(self, symbols: list[str]) -> None:
        norm = []
        for s in symbols[: self.MAX_SYMBOLS]:
            sym = str(s).upper()
            if not sym.endswith("USDT"):
                sym = f"{sym}USDT"
            norm.append(sym.lower())
        self._symbols = norm

    def get_kline_close(self, coin: str) -> float | None:
        sym = f"{str(coin).upper()}USDT"
        with self._lock:
            row = self._klines.get(sym)
            return float(row[-1]) if row else None

    def get_depth(self, coin: str) -> dict[str, Any] | None:
        sym = f"{str(coin).upper()}USDT"
        with self._lock:
            d = self._depth.get(sym)
            return dict(d) if d else None

    async def start(self, symbols: list[str] | None = None) -> None:
        if symbols:
            self.set_symbols(symbols)
        if not self._symbols:
            return
        if self._task and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="bn-core-stream")

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        self.connected = False

    def _stream_url(self) -> str:
        parts = []
        for sym in self._symbols:
            parts.append(f"{sym}@kline_1m")
            parts.append(f"{sym}@depth20@100ms")
        joined = "/".join(parts)
        return f"{ws_market_base()}/stream?streams={joined}"

    async def _run(self) -> None:
        backoff = self.RECONNECT_BASE
        while not self._stop.is_set():
            url = self._stream_url()
            try:
                async with websockets.connect(
                    url,
                    ping_interval=20,
                    ping_timeout=20,
                    close_timeout=5,
                    max_size=4 * 1024 * 1024,
                ) as ws:
                    self.connected = True
                    backoff = self.RECONNECT_BASE
                    log.info("core WS connected (%d symbols)", len(self._symbols))
                    async for raw in ws:
                        if self._stop.is_set():
                            break
                        self._handle(raw)
            except asyncio.CancelledError:
                raise
            except ConnectionClosed as exc:
                self.connected = False
                self.last_error = str(exc)[:120]
            except Exception as exc:
                self.connected = False
                self.last_error = str(exc)[:120]
            if self._stop.is_set():
                break
            self.reconnects += 1
            await asyncio.sleep(min(backoff, self.RECONNECT_MAX))
            backoff = min(backoff * 1.5, self.RECONNECT_MAX)

    def _handle(self, raw: str | bytes) -> None:
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            return
        stream = str(msg.get("stream") or "")
        data = msg.get("data")
        if not isinstance(data, dict):
            return
        sym = str(data.get("s") or "").upper()
        if "@kline" in stream or data.get("e") == "kline":
            k = data.get("k") or {}
            close = float(k.get("c") or 0)
            if close > 0 and sym:
                with self._lock:
                    self._klines[sym] = [close]
            return
        if "depth" in stream or data.get("e") == "depthUpdate":
            bids = data.get("b") or data.get("bids") or []
            asks = data.get("a") or data.get("asks") or []
            with self._lock:
                self._depth[sym] = {
                    "bids": bids[:5],
                    "asks": asks[:5],
                    "ts": int(time.time() * 1000),
                }

    def status(self) -> dict[str, Any]:
        with self._lock:
            nk = len(self._klines)
            nd = len(self._depth)
        return {
            "connected": self.connected,
            "symbols": len(self._symbols),
            "klines": nk,
            "depth": nd,
            "reconnects": self.reconnects,
            "last_error": self.last_error,
        }
