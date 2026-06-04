"""MEGA Phase-1 async hub — dedicated UDS + açık coin mark WS (REST reconcile soğuk)."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
from typing import Any

import websockets
from websockets.exceptions import ConnectionClosed

from binance_futures_trader.async_hub.price_cache import HotPriceCache
from binance_futures_trader.async_hub.user_data_stream import UserDataStream

log = logging.getLogger("mega.async_hub")

_hub: "MegaAsyncHub | None" = None
_hub_lock = threading.Lock()


def mega_hub_enabled() -> bool:
    return os.getenv("MEGA_ASYNC_HUB", "").strip().lower() in ("1", "true", "yes", "on")


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, str(default)))
    except ValueError:
        return default


def _mega_rest_base() -> str:
    try:
        from elite_trader.mega_live import mega_binance_env

        rest = mega_binance_env("BINANCE_FUTURES_REST_BASE")
    except Exception:
        rest = os.getenv("MEGA_BINANCE_FUTURES_REST_BASE", "").strip()
    if rest:
        return rest.rstrip("/")
    try:
        from elite_trader.mega_live import get_mega_client

        mc = get_mega_client()
        base = getattr(mc, "_rest_base", None) or getattr(mc, "rest_base", None)
        if base:
            return str(base).rstrip("/")
    except Exception:
        pass
    from binance_futures_trader.client import api_base

    return api_base().rstrip("/")


def _mega_ws_base() -> str:
    """UDS listenKey WS — demo-fapi REST ile eşleşen user stream."""
    explicit = os.getenv("MEGA_BINANCE_FUTURES_WS_BASE", "").strip()
    if explicit:
        return explicit.rstrip("/")
    rest = _mega_rest_base().lower()
    demo = os.getenv("MEGA_BINANCE_FUTURES_DEMO", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    if demo or "demo-fapi" in rest:
        return "wss://fstream.binance.com"
    if "testnet.binancefuture.com" in rest or (
        "binancefuture.com" in rest and "demo-fapi" not in rest
    ):
        return "wss://fstream.binancefuture.com"
    return "wss://fstream.binance.com"


def _mega_mark_ws_base() -> str:
    """Kamu mark/book WS — demo-fapi ile mark_ws ile aynı: fstream.binance.com."""
    explicit = os.getenv("MEGA_MARK_WS_BASE", "").strip()
    if explicit:
        return explicit.rstrip("/")
    try:
        from binance_futures_trader.mark_ws import ws_base as _bn_mark_ws_base

        return _bn_mark_ws_base().rstrip("/")
    except Exception:
        pass
    rest = _mega_rest_base().lower()
    demo = os.getenv("MEGA_BINANCE_FUTURES_DEMO", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    if demo or "demo-fapi" in rest:
        return "wss://fstream.binance.com"
    return _mega_ws_base()


def _mega_ws_fallbacks(primary: str | None = None) -> list[str]:
    """UDS bağlı ama event gelmezse alternatif demo WS dene."""
    primary = (primary or _mega_ws_base()).rstrip("/")
    bases = [primary]
    rest = _mega_rest_base().lower()
    demo = os.getenv("MEGA_BINANCE_FUTURES_DEMO", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    if demo or "demo-fapi" in rest:
        alt = "wss://fstream.binancefuture.com"
        if alt not in bases:
            bases.append(alt)
    return bases


class MegaOpenMarkStream:
    """Açık pozisyon coinleri için markPrice@1s combined stream."""

    MAX_SYMBOLS = 16
    RECONNECT_BASE = 0.8
    RECONNECT_MAX = 20.0

    def __init__(self, cache: HotPriceCache, ws_base: str) -> None:
        self.cache = cache
        self._ws_base = ws_base.rstrip("/")
        self._symbols: tuple[str, ...] = ()
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._rev = 0
        self.connected = False
        self.reconnects = 0
        self.last_error: str | None = None

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="mega-mark-stream")

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

    async def set_symbols(self, coins: list[str]) -> None:
        syms = tuple(
            sorted(
                {
                    str(c or "").upper().replace("USDT", "").strip()
                    for c in coins
                    if str(c or "").strip()
                }
            )[: self.MAX_SYMBOLS]
        )
        if syms != self._symbols:
            self._symbols = syms
            self._rev += 1

    async def _run(self) -> None:
        backoff = self.RECONNECT_BASE
        use_book = os.getenv("MEGA_MARK_WS_SOURCE", "bookticker").strip().lower() in (
            "book",
            "bookticker",
            "book_ticker",
        )
        while not self._stop.is_set():
            if not self._symbols:
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=0.6)
                    break
                except asyncio.TimeoutError:
                    continue
            rev = self._rev
            if use_book:
                streams = "/".join(
                    f"{s.lower()}usdt@bookTicker" for s in self._symbols
                )
            else:
                streams = "/".join(
                    f"{s.lower()}usdt@markPrice@1s" for s in self._symbols
                )
            url = f"{self._ws_base}/stream?streams={streams}"
            try:
                async with websockets.connect(
                    url,
                    ping_interval=20,
                    ping_timeout=20,
                    close_timeout=5,
                ) as ws:
                    self.connected = True
                    backoff = self.RECONNECT_BASE
                    log.info("MEGA mark stream: %s coin", len(self._symbols))
                    async for raw in ws:
                        if self._stop.is_set() or rev != self._rev:
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
            if rev != self._rev:
                continue
            self.reconnects += 1
            await asyncio.sleep(min(backoff, self.RECONNECT_MAX))
            backoff = min(backoff * 1.4, self.RECONNECT_MAX)

    def _handle(self, raw: str | bytes) -> None:
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            return
        data = msg.get("data") if isinstance(msg.get("data"), dict) else msg
        sym = str(data.get("s") or data.get("symbol") or "")
        bid = float(data.get("b") or data.get("bidPrice") or 0)
        ask = float(data.get("a") or data.get("askPrice") or 0)
        mark = float(data.get("p") or data.get("markPrice") or 0)
        if bid > 0 and ask > 0:
            mark = (bid + ask) / 2.0
        if mark <= 0 or not sym:
            return
        coin = sym.replace("USDT", "").upper()
        evt_ms = int(data.get("E") or data.get("T") or 0)
        if bid > 0 and ask > 0:
            self.cache.update_mid(coin, bid, ask, ts_ms=evt_ms or None)
        self.cache.update_mark(coin, mark, event_ms=evt_ms or None)
        try:
            from binance_futures_trader.fast_price_ws import ingest_mid

            ingest_mid(coin, bid if bid > 0 else mark, ask if ask > 0 else mark, evt_ms)
        except Exception:
            pass
        try:
            from elite_trader.mega_live import touch_mega_cache_from_hub_marks

            touch_mega_cache_from_hub_marks()
        except Exception:
            pass


class MegaAsyncHub:
    def __init__(self) -> None:
        self.cache = HotPriceCache()
        self._uds: UserDataStream | None = None
        self._mark: MegaOpenMarkStream | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._stop_flag = threading.Event()
        self._last_positions_ts = 0.0
        self._last_wallet_ts = 0.0
        self._last_reconcile = 0.0
        self._last_mark_touch_ts = 0.0
        self._ws_bases = _mega_ws_fallbacks(_mega_ws_base())
        self._ws_idx = 0

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_flag.clear()
        self._ready.clear()
        self._thread = threading.Thread(
            target=self._thread_main, name="mega-async-hub", daemon=True
        )
        self._thread.start()
        if not self._ready.wait(timeout=20.0):
            log.warning("MEGA async hub ready timeout")

    def stop(self) -> None:
        self._stop_flag.set()
        loop = self._loop
        if loop and loop.is_running():
            fut = asyncio.run_coroutine_threadsafe(self._async_stop(), loop)
            try:
                fut.result(timeout=4.0)
            except Exception:
                pass
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)
        self._thread = None
        self._loop = None

    def _thread_main(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        try:
            loop.run_until_complete(self._async_run())
        finally:
            try:
                loop.run_until_complete(self._async_stop())
            except Exception:
                pass
            loop.close()

    async def _async_run(self) -> None:
        try:
            from elite_trader.mega_live import mega_binance_env

            key = mega_binance_env("BINANCE_API_KEY")
        except Exception:
            key = os.getenv("MEGA_BINANCE_API_KEY", "").strip()
        if not key:
            log.warning("MEGA async hub: no BINANCE_API_KEY for instance")
            self._ready.set()
            return
        rest = _mega_rest_base()
        ws = self._ws_bases[self._ws_idx % len(self._ws_bases)]
        self._uds = UserDataStream(
            api_key=key,
            on_wallet=self._on_wallet,
            on_positions=self._on_positions,
            rest_base=rest,
            ws_base=ws,
        )
        self._mark = MegaOpenMarkStream(self.cache, _mega_mark_ws_base())
        await self._uds.start()
        await self._mark.start()
        try:
            await asyncio.to_thread(self._bootstrap_positions)
            coins = self._open_coins()
            if self._mark and coins:
                await self._mark.set_symbols(coins)
        except Exception as exc:
            log.warning("MEGA hub bootstrap: %s", exc)
        self._ready.set()
        log.info(
            "MEGA async hub started rest=%s uds_ws=%s mark_ws=%s",
            rest,
            ws,
            _mega_mark_ws_base(),
        )
        reconcile_sec = max(15.0, _env_float("MEGA_HUB_RECONCILE_SEC", 30.0))
        sym_iv = max(0.4, _env_float("MEGA_HUB_SYMBOL_POLL_SEC", 1.0))
        uds_watch_iv = max(60.0, _env_float("MEGA_HUB_UDS_WATCH_SEC", 120.0))
        hub_started = time.time()
        last_uds_watch = hub_started
        while not self._stop_flag.is_set():
            coins = self._open_coins()
            if self._mark:
                await self._mark.set_symbols(coins)
            now = time.time()
            if (
                self._uds
                and self._uds.connected
                and now - hub_started >= uds_watch_iv
            ):
                lag = self._uds.status().get("lag_ms")
                if (
                    lag is None
                    and now - last_uds_watch >= uds_watch_iv
                    and self._ws_bases
                    and len(self._ws_bases) > 1
                ):
                    last_uds_watch = now
                    self._ws_idx = (self._ws_idx + 1) % len(self._ws_bases)
                    log.warning(
                        "MEGA UDS no events — WS flip %s",
                        self._ws_bases[self._ws_idx],
                    )
                    await self._uds.stop()
                    self._uds = UserDataStream(
                        api_key=key,
                        on_wallet=self._on_wallet,
                        on_positions=self._on_positions,
                        rest_base=rest,
                        ws_base=self._ws_bases[self._ws_idx],
                    )
                    await self._uds.start()
                    try:
                        await asyncio.to_thread(self._bootstrap_positions)
                    except Exception as exc:
                        log.warning("MEGA hub re-bootstrap: %s", exc)
            if now - self._last_reconcile >= reconcile_sec:
                self._last_reconcile = now
                try:
                    await asyncio.to_thread(self._reconcile)
                except Exception as exc:
                    log.warning("MEGA hub reconcile: %s", exc)
            try:
                await asyncio.sleep(sym_iv)
            except asyncio.CancelledError:
                break

    async def _async_stop(self) -> None:
        if self._mark:
            await self._mark.stop()
        if self._uds:
            await self._uds.stop()

    def _bootstrap_positions(self) -> None:
        from elite_trader.mega_live import bootstrap_mega_hub_positions

        n = bootstrap_mega_hub_positions()
        if n:
            log.info("MEGA hub bootstrap: %s positions from REST", n)
            self._last_positions_ts = time.time()

    def _on_wallet(self, wallet: dict[str, Any]) -> None:
        from elite_trader.mega_live import apply_mega_uds_wallet

        apply_mega_uds_wallet(wallet)
        self._last_wallet_ts = time.time()

    def _on_positions(self, rows: list[dict[str, Any]]) -> None:
        from elite_trader.mega_live import apply_mega_uds_positions

        apply_mega_uds_positions(rows)
        self._last_positions_ts = time.time()

    def _open_coins(self) -> list[str]:
        from elite_trader.mega_live import mega_open_coins_for_hub

        return mega_open_coins_for_hub()

    def _reconcile(self) -> None:
        from elite_trader.mega_live import refresh_mega_positions_cache

        refresh_mega_positions_cache(force=True, skip_wallet=False)

    def status(self) -> dict[str, Any]:
        uds_st: dict[str, Any] = {}
        if self._uds:
            uds_st = self._uds.status()
        mark_st = {
            "connected": bool(self._mark and self._mark.connected),
            "reconnects": self._mark.reconnects if self._mark else 0,
            "last_error": self._mark.last_error if self._mark else None,
            "symbols": list(self._mark._symbols) if self._mark else [],
        }
        now = time.time()
        return {
            "enabled": mega_hub_enabled(),
            "alive": bool(self._thread and self._thread.is_alive()),
            "ready": self._ready.is_set(),
            "uds": uds_st,
            "mark": mark_st,
            "cache": self.cache.status(),
            "positions_age_ms": max(
                0, int((now - self._last_positions_ts) * 1000)
            )
            if self._last_positions_ts
            else None,
            "wallet_age_ms": max(0, int((now - self._last_wallet_ts) * 1000))
            if self._last_wallet_ts
            else None,
            "last_reconcile_ago_sec": round(now - self._last_reconcile, 1)
            if self._last_reconcile
            else None,
            "ws_base": self._ws_bases[self._ws_idx % len(self._ws_bases)]
            if self._ws_bases
            else None,
            "mark_ws": _mega_mark_ws_base(),
            "mark_touch_age_ms": max(
                0, int((now - self._last_mark_touch_ts) * 1000)
            )
            if self._last_mark_touch_ts
            else None,
        }


def get_mega_hub() -> MegaAsyncHub | None:
    return _hub


def start_mega_async_hub() -> None:
    ensure_mega_async_hub()


def ensure_mega_async_hub() -> None:
    """Hub thread ölü veya mark WS baygınsa yeniden başlat (mega-rest zaten çalışıyor olsa bile)."""
    global _hub
    if not mega_hub_enabled():
        return
    with _hub_lock:
        need_start = False
        force_restart = False
        if _hub is None:
            _hub = MegaAsyncHub()
            need_start = True
        else:
            st = _hub.status()
            if not bool(st.get("alive")):
                need_start = True
            elif bool(st.get("ready")):
                mark = st.get("mark") or {}
                cache = st.get("cache") or {}
                recv_lag = cache.get("lag_ms")
                mark_connected = bool(mark.get("connected"))
                stale_ms = max(
                    5000.0, _env_float("MEGA_HUB_STALE_RESTART_MS", 12000.0)
                )
                has_pos = False
                coins: list[str] = []
                try:
                    from elite_trader.mega_live import (
                        mega_open_coins_for_hub,
                        mega_positions_cache_nonempty,
                    )

                    has_pos = mega_positions_cache_nonempty()
                    coins = mega_open_coins_for_hub()
                except Exception:
                    pass
                if has_pos and coins and (
                    not mark_connected
                    or (
                        recv_lag is not None and float(recv_lag) >= stale_ms
                    )
                ):
                    force_restart = True
                    need_start = True
        if force_restart and _hub:
            try:
                _hub.stop()
            except Exception:
                pass
            _hub = MegaAsyncHub()
        if need_start and _hub:
            _hub.start()


def stop_mega_async_hub() -> None:
    global _hub
    with _hub_lock:
        if _hub:
            _hub.stop()
            _hub = None


def hub_mark_fresh(*, max_age_ms: float = 150.0) -> bool:
    hub = _hub
    if not hub or not mega_hub_enabled():
        return False
    st = hub.cache.status()
    lag = st.get("lag_ms")
    if lag is None:
        return False
    return bool(st.get("ok")) and float(lag) <= float(max_age_ms)


def hub_cache_hot(*, mark_max_ms: float | None = None) -> bool:
    """Mark WS taze + bootstrap/UDS pozisyon listesi — REST positionRisk atlanır."""
    hub = _hub
    if not hub or not mega_hub_enabled():
        return False
    from elite_trader.mega_live import mega_positions_cache_nonempty

    if not mega_positions_cache_nonempty():
        return False
    mark_ms = float(
        mark_max_ms if mark_max_ms is not None else _env_float("MEGA_HUB_MARK_FRESH_MS", 120.0)
    )
    if not hub_mark_fresh(max_age_ms=mark_ms):
        return False
    pos_ms = max(500.0, _env_float("MEGA_HUB_POS_FRESH_MS", 120_000.0))
    if not hub._last_positions_ts:
        return False
    return (time.time() - hub._last_positions_ts) * 1000.0 <= pos_ms


def note_hub_mark_touch() -> None:
    hub = _hub
    if hub:
        hub._last_mark_touch_ts = time.time()


def hub_positions_fresh(*, max_age_ms: float | None = None) -> bool:
    hub = _hub
    if not hub or not mega_hub_enabled():
        return False
    age_ms = max(200.0, _env_float("MEGA_HUB_FRESH_MS", 800.0))
    if max_age_ms is not None:
        age_ms = float(max_age_ms)
    if not hub._last_positions_ts:
        return False
    if (time.time() - hub._last_positions_ts) * 1000.0 > age_ms:
        return False
    uds = hub._uds
    if not uds or not uds.connected:
        return False
    return True


def hub_marks_snapshot(*, max_recv_age_sec: float = 2.0) -> tuple[dict[str, float], dict[str, Any]]:
    """Panel tick — hub mark WS önbelleği (positionRisk beklemeden)."""
    hub = _hub
    meta: dict[str, Any] = {
        "enabled": mega_hub_enabled(),
        "alive": False,
        "mark_lag_ms": None,
    }
    if not hub or not mega_hub_enabled():
        return {}, meta
    marks = hub.cache.get_all_marks_if_fresh(max_recv_age_sec=max_recv_age_sec) or {}
    st = hub.status()
    meta["alive"] = bool(st.get("alive"))
    cache = st.get("cache") or {}
    lag = cache.get("mark_lag_ms")
    if lag is None:
        lag = cache.get("lag_ms")
    if lag is not None:
        meta["mark_lag_ms"] = float(lag)
    return marks, meta


def overlay_hub_marks(cache: list[dict[str, Any]]) -> None:
    hub = _hub
    if not hub or not cache:
        return
    marks = hub.cache.get_all_marks_if_fresh(max_recv_age_sec=2.0)
    if not marks:
        return
    for ep in cache:
        coin = str(ep.get("coin") or "").upper()
        mark = marks.get(coin)
        if not mark or mark <= 0:
            continue
        # Mark WS yalnızca fiyat overlay — uPnL positionRisk unRealizedProfit ile kalmalı.
        ep["mark_price"] = float(mark)


def get_hub_book(coin: str, *, max_age_ms: float = 150.0) -> dict[str, Any] | None:
    """MEGA hub bookTicker önbelleği — emir öncesi REST bookTicker atla."""
    hub = _hub
    if not hub or not mega_hub_enabled():
        return None
    key = str(coin or "").upper().replace("USDT", "")
    if not key:
        return None
    mids = hub.cache.get_all_mids_snapshot(max_age_ms=max_age_ms)
    row = mids.get(key)
    if not row:
        return None
    mid = float(row.get("mid") or 0)
    if mid <= 0:
        return None
    return {
        "bid": float(row.get("bid") or mid),
        "ask": float(row.get("ask") or mid),
        "mid": mid,
        "ts_ms": int(row.get("ts_ms") or 0),
        "src": "mega_hub_book",
    }


def mega_hub_bookticker_status(*, max_stale_ms: float = 5000.0) -> dict[str, Any] | None:
    """connection/live bookticker — MEGA hub açık-coin bookTicker stream."""
    hub = _hub
    if not hub or not mega_hub_enabled():
        return None
    cache = hub.cache.status()
    mark_st = hub.status().get("mark") or {}
    recv_lag = cache.get("lag_ms")
    event_lag = cache.get("book_lag_ms")
    if event_lag is None:
        event_lag = cache.get("mark_lag_ms")
    n_coins = int(cache.get("mid_coins") or cache.get("mark_coins") or 0)
    connected = bool(mark_st.get("connected"))
    display_lag = event_lag if event_lag is not None else recv_lag
    stale = recv_lag is not None and float(recv_lag) >= float(max_stale_ms)
    if n_coins <= 0 and not connected:
        health = "disconnected"
    elif stale:
        health = "stale"
    elif connected or (
        n_coins > 0
        and recv_lag is not None
        and float(recv_lag) < float(max_stale_ms)
    ):
        health = "ok"
    else:
        health = "disconnected"
    return {
        "health": health,
        "source": "mega_hub_book",
        "lag_ms": int(display_lag) if display_lag is not None else None,
        "event_lag_ms": int(event_lag) if event_lag is not None else None,
        "recv_lag_ms": int(recv_lag) if recv_lag is not None else None,
        "coins": n_coins,
        "connected": connected,
    }


def mega_hub_mark_ws_status(*, max_stale_ms: float = 5000.0) -> dict[str, Any] | None:
    """connection/live mark_ws — MEGA açık-coin mark stream (hub publisher bookticker değil)."""
    hub = _hub
    if not hub or not mega_hub_enabled():
        return None
    cache = hub.cache.status()
    mark_st = hub.status().get("mark") or {}
    recv_lag = cache.get("lag_ms")
    event_lag = cache.get("mark_lag_ms")
    if event_lag is None:
        event_lag = cache.get("book_lag_ms")
    n_coins = int(cache.get("mark_coins") or 0)
    connected = bool(mark_st.get("connected"))
    display_lag = event_lag if event_lag is not None else recv_lag
    stale = recv_lag is not None and float(recv_lag) >= float(max_stale_ms)
    if n_coins <= 0 and not connected:
        health = "disconnected"
    elif stale:
        health = "stale"
    elif connected or (
        n_coins > 0
        and recv_lag is not None
        and float(recv_lag) < float(max_stale_ms)
    ):
        health = "ok"
    else:
        health = "disconnected"
    return {
        "health": health,
        "source": "mega_hub_mark_ws",
        "lag_ms": int(display_lag) if display_lag is not None else None,
        "event_lag_ms": int(event_lag) if event_lag is not None else None,
        "recv_lag_ms": int(recv_lag) if recv_lag is not None else None,
        "coins": n_coins,
        "connected": connected,
    }


def mega_hub_status() -> dict[str, Any]:
    hub = _hub
    if not hub:
        return {"enabled": mega_hub_enabled(), "alive": False}
    return hub.status()
