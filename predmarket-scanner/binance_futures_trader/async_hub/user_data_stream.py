"""Binance Futures User Data Stream — listenKey + ACCOUNT/ORDER events."""
from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from typing import Any, Callable

import httpx
import websockets
from websockets.exceptions import ConnectionClosed

from binance_futures_trader.async_hub.ws_urls import ws_user_base
from binance_futures_trader.client import api_base
from binance_futures_trader.network_ssl import httpx_verify

log = logging.getLogger("bn.async_hub.uds")

WalletCallback = Callable[[dict[str, Any]], None]
PositionsCallback = Callable[[list[dict[str, Any]]], None]


class UserDataStream:
    KEEPALIVE_SEC = 25 * 60
    RECONNECT_BASE = 5.0
    RECONNECT_MAX = 120.0
    RATE_LIMIT_BACKOFF = 90.0

    def __init__(
        self,
        *,
        api_key: str,
        on_wallet: WalletCallback | None = None,
        on_positions: PositionsCallback | None = None,
        rest_base: str | None = None,
        ws_base: str | None = None,
    ) -> None:
        self.api_key = (api_key or "").strip()
        self.on_wallet = on_wallet
        self.on_positions = on_positions
        self._rest_base = (rest_base or api_base()).rstrip("/")
        self._ws_base = (ws_base or ws_user_base()).rstrip("/")
        self._listen_key: str | None = None
        self._task: asyncio.Task | None = None
        self._keepalive_task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self.connected = False
        self.reconnects = 0
        self.last_event_ms: int = 0
        self.last_error: str | None = None
        self._positions: list[dict[str, Any]] = []
        self._positions_map: dict[str, dict[str, Any]] = {}
        self._wallet: dict[str, Any] | None = None
        self._lock = threading.Lock()

    def get_wallet(self) -> dict[str, Any] | None:
        with self._lock:
            return dict(self._wallet) if self._wallet else None

    def get_positions(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._positions)

    def load_positions(self, rows: list[dict[str, Any]]) -> None:
        """REST bootstrap — tam açık pozisyon listesi (UDS başlangıç snapshot)."""
        with self._lock:
            self._positions_map.clear()
            for row in rows or []:
                parsed = self._parse_position_row(row)
                if parsed:
                    self._positions_map[parsed["symbol"]] = parsed
            self._positions = list(self._positions_map.values())
        if self.on_positions:
            self.on_positions(list(self._positions))

    async def start(self) -> None:
        if not self.api_key:
            self.last_error = "no api key"
            return
        if self._task and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="bn-user-data-stream")
        self._keepalive_task = asyncio.create_task(
            self._keepalive_loop(), name="bn-uds-keepalive"
        )

    async def stop(self) -> None:
        self._stop.set()
        for t in (self._task, self._keepalive_task):
            if t:
                t.cancel()
                try:
                    await t
                except asyncio.CancelledError:
                    pass
        self._task = None
        self._keepalive_task = None
        await self._close_listen_key()
        self.connected = False

    async def _http_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self._rest_base,
            timeout=httpx.Timeout(15.0, connect=10.0),
            verify=httpx_verify(),
            headers={
                "X-MBX-APIKEY": self.api_key,
                "User-Agent": "bn-fut-async-hub/1.0",
            },
        )

    def _rest_blocked(self) -> bool:
        try:
            from elite_trader.network_guard import skip_rest

            return skip_rest()
        except Exception:
            return False

    def _backoff_sec(self, exc: Exception | None = None) -> float:
        text = str(exc or self.last_error or "")
        if any(x in text for x in ("418", "429", "-1003", "Too Many Requests")):
            try:
                from elite_trader.network_guard import degraded_remaining_sec

                return max(self.RATE_LIMIT_BACKOFF, degraded_remaining_sec())
            except Exception:
                return self.RATE_LIMIT_BACKOFF
        if self._rest_blocked():
            try:
                from elite_trader.network_guard import degraded_remaining_sec

                return max(30.0, degraded_remaining_sec())
            except Exception:
                return 30.0
        return self.RECONNECT_BASE

    async def _create_listen_key(self) -> str | None:
        if self._rest_blocked():
            self.last_error = "listenKey skipped: REST degraded/ban"
            return None
        try:
            async with await self._http_client() as client:
                r = await client.post("/fapi/v1/listenKey")
                r.raise_for_status()
                data = r.json()
                key = str(data.get("listenKey") or "")
                if key:
                    try:
                        from elite_trader.connection_alerts import note_binance_success

                        note_binance_success()
                    except Exception:
                        pass
                return key or None
        except Exception as exc:
            self.last_error = f"listenKey create: {exc}"[:120]
            log.warning("%s", self.last_error)
            try:
                from elite_trader.connection_alerts import note_binance_error

                note_binance_error(self.last_error)
            except Exception:
                pass
            return None

    async def _keepalive_listen_key(self) -> bool:
        if not self._listen_key or self._rest_blocked():
            return False
        try:
            async with await self._http_client() as client:
                r = await client.put(
                    "/fapi/v1/listenKey",
                    params={"listenKey": self._listen_key},
                )
                r.raise_for_status()
                return True
        except Exception as exc:
            self.last_error = f"listenKey keepalive: {exc}"[:120]
            try:
                from elite_trader.connection_alerts import note_binance_error

                note_binance_error(self.last_error)
            except Exception:
                pass
            return False

    async def _close_listen_key(self) -> None:
        if not self._listen_key:
            return
        key = self._listen_key
        self._listen_key = None
        try:
            async with await self._http_client() as client:
                await client.delete(
                    "/fapi/v1/listenKey",
                    params={"listenKey": key},
                )
        except Exception:
            pass

    async def _keepalive_loop(self) -> None:
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.KEEPALIVE_SEC)
                break
            except asyncio.TimeoutError:
                pass
            if self._listen_key:
                await self._keepalive_listen_key()

    async def _run(self) -> None:
        backoff = self.RECONNECT_BASE
        while not self._stop.is_set():
            if self._rest_blocked():
                wait = self._backoff_sec()
                log.info("UDS REST blocked — %ss bekleniyor", round(wait, 1))
                await asyncio.sleep(wait)
                continue
            key = await self._create_listen_key()
            if not key:
                wait = self._backoff_sec(Exception(self.last_error or ""))
                await asyncio.sleep(min(wait, self.RECONNECT_MAX))
                backoff = min(max(backoff * 1.5, wait), self.RECONNECT_MAX)
                continue
            self._listen_key = key
            url = f"{self._ws_base}/ws/{key}"
            try:
                async with websockets.connect(
                    url,
                    ping_interval=20,
                    ping_timeout=20,
                    close_timeout=5,
                ) as ws:
                    self.connected = True
                    backoff = self.RECONNECT_BASE
                    log.info("user data stream connected")
                    async for raw in ws:
                        if self._stop.is_set():
                            break
                        self._handle_event(raw)
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

    def _handle_event(self, raw: str | bytes) -> None:
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            return
        self.last_event_ms = int(time.time() * 1000)
        et = str(msg.get("e") or "")
        if et == "ACCOUNT_UPDATE":
            self._on_account_update(msg)
        elif et == "ORDER_TRADE_UPDATE":
            self._on_order_trade_update(msg)

    def _on_account_update(self, msg: dict[str, Any]) -> None:
        acct = msg.get("a") or {}
        balances = acct.get("B") or []
        positions = acct.get("P")
        wallet: dict[str, Any] = {}
        for b in balances:
            if str(b.get("a") or "").upper() == "USDT":
                wb = float(b.get("wb") or 0)
                cw = float(b.get("cw") or wb)
                wallet = {
                    "total_wallet_balance": round(wb, 4),
                    "available_balance": round(cw, 4),
                    "total_margin_balance": round(wb, 4),
                    "usdt_balance": round(wb, 4),
                    "usdt_available": round(cw, 4),
                    "source": "uds",
                }
                break
        pos_changed = False
        if positions:
            pos_changed = self._merge_position_rows(positions)
        with self._lock:
            if wallet:
                self._wallet = wallet
        if wallet and self.on_wallet:
            self.on_wallet(wallet)
        if pos_changed:
            with self._lock:
                merged = list(self._positions_map.values())
                self._positions = merged
            if self.on_positions:
                self.on_positions(merged)

    def _on_order_trade_update(self, msg: dict[str, Any]) -> None:
        # ORDER events may carry position hints; full reconcile stays on REST cold path.
        o = msg.get("o") or {}
        if str(o.get("x") or "") not in ("TRADE", "NEW", "CANCELED", "EXPIRED"):
            return
        self.last_event_ms = int(time.time() * 1000)

    def _parse_position_row(self, p: dict[str, Any]) -> dict[str, Any] | None:
        amt = float(p.get("pa") or p.get("positionAmt") or p.get("contracts") or 0)
        sym = str(p.get("s") or p.get("symbol") or "")
        if not sym:
            coin = str(p.get("coin") or "").upper()
            sym = f"{coin}USDT" if coin else ""
        if not sym:
            return None
        coin = sym.replace("USDT", "")
        if abs(amt) < 1e-12:
            return None
        side = str(p.get("side") or ("LONG" if amt > 0 else "SHORT")).upper()
        if side not in ("LONG", "SHORT"):
            side = "LONG" if amt > 0 else "SHORT"
        entry = float(p.get("ep") or p.get("entryPrice") or p.get("entry_price") or 0)
        mark = float(p.get("mp") or p.get("markPrice") or p.get("mark_price") or 0)
        upnl = float(p.get("up") or p.get("unRealizedProfit") or p.get("unrealized_pnl") or 0)
        return {
            "coin": coin,
            "symbol": sym,
            "side": side,
            "contracts": abs(amt),
            "entry_price": entry,
            "mark_price": mark,
            "unrealized_pnl": upnl,
            "source": "uds",
        }

    def _merge_position_rows(self, rows: list[dict[str, Any]]) -> bool:
        """Binance UDS — P yalnızca değişen sembolleri içerir; birleştir."""
        changed = False
        with self._lock:
            for p in rows or []:
                sym = str(p.get("s") or p.get("symbol") or "")
                if not sym:
                    continue
                amt = float(p.get("pa") or p.get("positionAmt") or 0)
                if abs(amt) < 1e-12:
                    if sym in self._positions_map:
                        del self._positions_map[sym]
                        changed = True
                    continue
                parsed = self._parse_position_row(p)
                if not parsed:
                    continue
                prev = self._positions_map.get(sym)
                if prev != parsed:
                    self._positions_map[sym] = parsed
                    changed = True
        return changed

    def _parse_positions(
        self, rows: list[dict[str, Any]]
    ) -> list[dict[str, Any]] | None:
        if rows is None:
            return None
        out: list[dict[str, Any]] = []
        for p in rows:
            parsed = self._parse_position_row(p)
            if parsed:
                out.append(parsed)
        return out

    def status(self) -> dict[str, Any]:
        now_ms = int(time.time() * 1000)
        lag = (now_ms - self.last_event_ms) if self.last_event_ms else None
        return {
            "connected": self.connected,
            "reconnects": self.reconnects,
            "lag_ms": lag,
            "last_error": self.last_error,
            "positions": len(self._positions),
            "has_wallet": bool(self._wallet),
        }
