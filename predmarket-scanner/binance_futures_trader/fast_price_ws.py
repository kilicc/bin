"""Binance Futures bookTicker WebSocket — sub-saniye bid/ask fiyatı.

bookTicker, her bid/ask değişiminde anında güncelleme gönderir (~10-200ms).
Aktif pozisyonlar için TP/SL kontrolünde kullanılır.

Kullanım:
    from binance_futures_trader.fast_price_ws import (
        get_fast_price, subscribe_symbols, fast_feed_status
    )
"""
from __future__ import annotations

import os
import threading
import time
import json
from typing import Any

from binance_futures_trader.network_ssl import ws_sslopt

_MAX_SYMBOLS      = 50          # subscribe_symbols izleme listesi (rapor)
_RECONNECT_MAX    = 10.0        # maks bekleme (sn)
_WS_GIVEUP_AFTER  = 5
_MAX_CACHE        = 150         # !bookTicker LRU önbellek


def _stale_sec() -> float:
    try:
        return max(2.0, float(os.getenv("BN_FUT_FAST_WS_STALE_SEC", "12")))
    except ValueError:
        return 12.0


def _watchdog_sec() -> float:
    try:
        return max(3.0, float(os.getenv("BN_FUT_FAST_WS_WATCHDOG_SEC", "8")))
    except ValueError:
        return 8.0


def _slow_interval() -> float:
    try:
        return max(8.0, float(os.getenv("BN_FUT_FAST_WS_SLOW_SEC", "15")))
    except ValueError:
        return 15.0


def _max_cache() -> int:
    try:
        return max(40, int(os.getenv("BN_FUT_FAST_WS_MAX_CACHE", str(_MAX_CACHE))))
    except ValueError:
        return _MAX_CACHE

try:
    from websocket import WebSocketApp
except ImportError:
    WebSocketApp = None  # type: ignore

_lock        = threading.Lock()
_prices: dict[str, dict] = {}   # coin → {bid, ask, mid, ts_ms}
_last_recv_ms: int = 0          # son fiyat güncellemesi (coin bazlı)
_last_ws_frame_ms: int = 0      # son WS mesajı (bağlantı canlılığı)
_reconnects: int  = 0
_connected        = False
_subscribed: set[str] = set()   # aktif takip listesi
_thread: threading.Thread | None = None
_stop     = threading.Event()
_ws_ref: Any = None
_started  = False
_ws_url_used: str = ""
_mark_bridge_hits: int = 0


def _ws_url_pool() -> list[str]:
    """Demo/testnet — mark_ws ile aynı URL havuzu."""
    try:
        from binance_futures_trader.mark_ws import (
            DEMO_WS_SECONDARY,
            MAIN_WS,
            TESTNET_WS,
            _demo_ws_pool,
            _is_demo,
            ws_base,
        )

        if _is_demo():
            return _demo_ws_pool()
        base = ws_base()
        if base == TESTNET_WS:
            return [TESTNET_WS, DEMO_WS_SECONDARY]
        return [base, MAIN_WS]
    except Exception:
        return ["wss://fstream.binance.com", "wss://fstream.binancefuture.com"]


def ingest_mid(coin: str, bid: float, ask: float, ts_ms: int | None = None) -> None:
    """Mark WS köprüsü — bookTicker yokken sub-s mid beslemesi."""
    global _last_recv_ms, _last_ws_frame_ms, _connected, _mark_bridge_hits
    try:
        b = float(bid)
        a = float(ask)
        if b <= 0 or a <= 0:
            return
        mid = (b + a) / 2
        ts = int(ts_ms or time.time() * 1000)
        key = str(coin).upper().replace("USDT", "")
        now_ms = int(time.time() * 1000)
        with _lock:
            _prices[key] = {"bid": b, "ask": a, "mid": mid, "ts_ms": ts, "src": "mark"}
            _last_recv_ms = ts
            _last_ws_frame_ms = now_ms
            _mark_bridge_hits += 1
            _trim_price_cache()
        _connected = True
    except (TypeError, ValueError):
        pass


# ── Sembol yönetimi ───────────────────────────────────────────────────────────

def subscribe_symbols(coins: list[str]) -> None:
    """İzlenecek coin listesini güncelle (büyük harf, USDT hariç)."""
    global _subscribed
    with _lock:
        new_set = {c.upper() for c in coins if c}
        if new_set == _subscribed:
            return
        _subscribed = new_set
    # !bookTicker akışı sabit — yeniden bağlanmaya gerek yok


def _get_subscribed() -> list[str]:
    with _lock:
        return list(_subscribed)[:_MAX_SYMBOLS]


# ── Fiyat okuma ───────────────────────────────────────────────────────────────

def _mega_hub_mids(*, max_age_ms: float) -> dict[str, dict]:
    """MEGA hub bookTicker — global !bookTicker'dan daha taze olabilir."""
    try:
        from elite_trader.mega_async_hub import mega_hub_enabled

        if not mega_hub_enabled():
            return {}
        from elite_trader import mega_async_hub as mah

        hub = mah._hub
        if not hub:
            return {}
        snap = hub.cache.get_all_mids_snapshot(max_age_ms=max_age_ms)
        return {k: dict(v) for k, v in snap.items() if v.get("mid")}
    except Exception:
        return {}


def get_all_fast_prices(*, max_age_ms: float = 3000) -> dict[str, dict]:
    """Tüm takip edilen coinlerin güncel fiyatları."""
    try:
        from binance_futures_trader.async_hub import get_orchestrator, is_async_hub_enabled

        if is_async_hub_enabled():
            orch = get_orchestrator()
            if orch:
                snap = orch.get_all_mids_if_fresh(max_age_ms=max_age_ms)
                if snap:
                    return snap
                bulk = orch.get_all_prices_bulk(max_recv_age_sec=max(1.0, max_age_ms / 1000.0))
                if bulk:
                    now_ms = int(time.time() * 1000)
                    return {
                        k: {"bid": v, "ask": v, "mid": v, "ts_ms": now_ms}
                        for k, v in bulk.items()
                        if v and float(v) > 0
                    }
    except Exception:
        pass
    hub_snap = _mega_hub_mids(max_age_ms=max_age_ms)
    now_ms = int(time.time() * 1000)
    with _lock:
        local = {
            c: dict(d)
            for c, d in _prices.items()
            if (now_ms - d["ts_ms"]) <= max_age_ms
        }
    if not hub_snap:
        return local
    out = dict(hub_snap)
    for c, d in local.items():
        if c not in out or int(d.get("ts_ms") or 0) > int(out[c].get("ts_ms") or 0):
            out[c] = d
    return out


def get_fast_price(coin: str, *, max_age_ms: float = 3000) -> dict | None:
    """Coin için en güncel bid/ask; yoksa None."""
    bulk = get_all_fast_prices(max_age_ms=max_age_ms)
    d = bulk.get(str(coin).upper())
    if d:
        return dict(d)
    now_ms = int(time.time() * 1000)
    with _lock:
        d = _prices.get(coin.upper())
    if d and (now_ms - d["ts_ms"]) <= max_age_ms:
        return dict(d)
    return None


def get_mid_price(coin: str, *, max_age_ms: float = 3000) -> float | None:
    """Mid fiyat (ask+bid)/2 — yoksa None."""
    d = get_fast_price(coin, max_age_ms=max_age_ms)
    return d["mid"] if d else None


# ── WebSocket ─────────────────────────────────────────────────────────────────

def _stream_url(base: str) -> str:
    return f"{base.rstrip('/')}/ws/!bookTicker"


def _trim_price_cache() -> None:
    cap = _max_cache()
    if len(_prices) <= cap:
        return
    drop = sorted(_prices.items(), key=lambda x: int(x[1].get("ts_ms") or 0))
    for k, _ in drop[: len(_prices) - cap]:
        _prices.pop(k, None)


def _ingest(payload: dict) -> None:
    global _last_recv_ms, _last_ws_frame_ms, _connected
    sym = str(payload.get("s") or "")
    if not sym.endswith("USDT"):
        return
    coin = sym.replace("USDT", "").upper()
    try:
        bid = float(payload.get("b") or 0)
        ask = float(payload.get("a") or 0)
        if bid <= 0 or ask <= 0:
            return
        mid = (bid + ask) / 2
        evt = int(payload.get("E") or payload.get("T") or 0)
        ts = evt if evt > 1_000_000_000_000 else int(time.time() * 1000)
        with _lock:
            _last_ws_frame_ms = int(time.time() * 1000)
            _prices[coin] = {"bid": bid, "ask": ask, "mid": mid, "ts_ms": ts, "src": "book"}
            _last_recv_ms = ts
            _trim_price_cache()
        _connected = True
    except (TypeError, ValueError):
        pass


def _on_message(_ws: Any, raw: str) -> None:
    try:
        msg = json.loads(raw)
    except Exception:
        return
    if isinstance(msg, dict):
        data = msg.get("data", msg)
        if isinstance(data, dict):
            _ingest(data)
            return
    if isinstance(msg, list):
        for row in msg:
            if isinstance(row, dict):
                _ingest(row)


def _on_open(_ws: Any) -> None:
    global _connected, _last_ws_frame_ms
    _connected = True
    _last_ws_frame_ms = int(time.time() * 1000)


def _on_close(_ws: Any, *_) -> None:
    global _connected, _reconnects
    _connected = False
    _reconnects += 1


def _on_error(_ws: Any, err: Any) -> None:
    global _connected
    _connected = False


def _kill_ws() -> None:
    ref = _ws_ref
    if ref:
        try:
            ref.close()
        except Exception:
            pass


def _run_loop() -> None:
    global _connected, _reconnects, _ws_ref, _ws_url_used
    backoff = 1.0
    fail_count = 0
    url_pool = _ws_url_pool()
    url_idx = 0

    while not _stop.is_set():
        if WebSocketApp is None:
            _stop.wait(30)
            return

        base = url_pool[url_idx % len(url_pool)]
        url = _stream_url(base)
        _ws_url_used = url
        try:
            app = WebSocketApp(
                url,
                on_open=_on_open,
                on_message=_on_message,
                on_error=_on_error,
                on_close=_on_close,
            )
            _ws_ref = app
            ssl_opt = ws_sslopt()

            old_env = dict(os.environ)
            for k in list(os.environ.keys()):
                if k.lower() in {"http_proxy", "https_proxy", "all_proxy",
                                  "socks_proxy", "socks5_proxy"}:
                    os.environ.pop(k, None)
            try:
                app.run_forever(ping_interval=20, ping_timeout=15, sslopt=ssl_opt)
            finally:
                for k, v in old_env.items():
                    os.environ[k] = v
                _ws_ref = None

        except Exception as exc:
            print(f"  ⚠ bookTicker WS ({base}): {str(exc)[:80]}")

        _connected = False
        _reconnects += 1
        fail_count += 1
        if _stop.is_set():
            break

        url_idx += 1
        if fail_count >= _WS_GIVEUP_AFTER:
            wait = _slow_interval()
        else:
            wait = min(backoff, _RECONNECT_MAX)
            backoff = min(backoff * 1.5, _RECONNECT_MAX)
        _stop.wait(wait)


# ── Watchdog ─────────────────────────────────────────────────────────────────

def _watchdog() -> None:
    while not _stop.is_set():
        _stop.wait(_watchdog_sec())
        if _stop.is_set():
            break
        now_ms = int(time.time() * 1000)
        with _lock:
            last = _last_ws_frame_ms or _last_recv_ms
        stale_ms = int(_stale_sec() * 1000)
        if _connected and last and (now_ms - last) > stale_ms:
            _kill_ws()


# ── Başlatma ─────────────────────────────────────────────────────────────────

def _fast_ws_enabled() -> bool:
    return os.getenv("BN_FUT_FAST_WS", "1").strip().lower() in ("1", "true", "yes")


def ensure_fast_feed_started(coins: list[str] | None = None) -> None:
    global _thread, _started
    try:
        from elite_trader.binance_data_hub import hub_consumer_mode

        if hub_consumer_mode():
            return
    except ImportError:
        pass
    if not _fast_ws_enabled():
        return
    try:
        from binance_futures_trader.async_hub import is_async_hub_enabled

        if is_async_hub_enabled():
            if coins:
                subscribe_symbols(coins)
            return
    except Exception:
        pass
    if coins:
        subscribe_symbols(coins)
    if _started and _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_run_loop, name="bn-fast-ws", daemon=True)
    _thread.start()
    threading.Thread(target=_watchdog, name="bn-fast-wd", daemon=True).start()
    _started = True


def stop_fast_feed() -> None:
    _stop.set()
    global _connected
    _connected = False
    _kill_ws()


def force_reconnect() -> None:
    """bookTicker WS — zorla yeniden bağlan."""
    global _connected, _reconnects
    _connected = False
    _reconnects += 1
    _kill_ws()


# ── Durum ────────────────────────────────────────────────────────────────────

def fast_feed_status() -> dict[str, Any]:
    try:
        from binance_futures_trader.async_hub import get_orchestrator, is_async_hub_enabled

        if is_async_hub_enabled():
            orch = get_orchestrator()
            if orch:
                st = orch.market.status()
                return {
                    "enabled": True,
                    "connected": bool(st.get("connected")),
                    "coins": int(st.get("mid_coins") or st.get("mark_coins") or 0),
                    "tracking": [],
                    "lag_ms": st.get("lag_ms"),
                    "reconnects": st.get("reconnects", 0),
                    "stale_sec": _stale_sec(),
                    "source": "async_hub",
                }
    except Exception:
        pass
    hub_bt: dict[str, Any] | None = None
    try:
        from elite_trader.mega_async_hub import mega_hub_bookticker_status

        hub_bt = mega_hub_bookticker_status()
    except Exception:
        hub_bt = None
    now_ms = int(time.time() * 1000)
    stale_ms = int(_stale_sec() * 1000)
    with _lock:
        n = len(_prices)
        price_last = _last_recv_ms
        ws_last = _last_ws_frame_ms or price_last
        ws_lag = (now_ms - ws_last) if ws_last else None
        price_lag = (now_ms - price_last) if price_last else None
        tracking = list(_subscribed)
        bridge = _mark_bridge_hits
        book_n = sum(1 for d in _prices.values() if d.get("src") == "book")
    ok = ws_lag is not None and ws_lag < stale_ms and (n > 0 or book_n > 0 or bridge > 0)
    lag = ws_lag
    src = "bookticker" if book_n > 0 else ("mark_bridge" if bridge > 0 else "none")
    if hub_bt and hub_bt.get("health") == "ok":
        hub_lag = hub_bt.get("lag_ms")
        if hub_lag is not None and (lag is None or int(hub_lag) < int(lag)):
            lag = hub_lag
            ok = True
            src = "mega_hub_book"
            n = max(n, int(hub_bt.get("coins") or 0))
    return {
        "enabled": _started and _fast_ws_enabled(),
        "connected": ok,
        "coins": n,
        "book_coins": book_n,
        "tracking": tracking,
        "lag_ms": lag,
        "price_lag_ms": price_lag,
        "ws_lag_ms": ws_lag,
        "reconnects": _reconnects,
        "stale_sec": _stale_sec(),
        "url": _ws_url_used,
        "source": src,
        "mark_bridge_hits": bridge,
        "hub_book": hub_bt,
    }
