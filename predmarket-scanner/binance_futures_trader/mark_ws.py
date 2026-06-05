"""Binance Futures mark price — WS öncelikli, REST fallback.

Ağ ortamı WS'e izin vermiyorsa (Connection refused / handshake timeout),
fiyatlar REST poller tarafından beslenir; bu modül REST fiyatlarını da kabul eder.
"""
from __future__ import annotations

import json
import os
import threading
import time
from typing import Any

from binance_futures_trader import config as cfg
from binance_futures_trader.client import api_base
from binance_futures_trader.network_ssl import ws_sslopt

try:
    from websocket import WebSocketApp
except ImportError:
    WebSocketApp = None  # type: ignore[misc, assignment]

MAIN_WS    = "wss://fstream.binance.com"
TESTNET_WS = "wss://fstream.binancefuture.com"
DEMO_WS_PRIMARY   = "wss://fstream.binance.com"
DEMO_WS_SECONDARY = "wss://fstream.binancefuture.com"


def _demo_ws_pool() -> list[str]:
    """Demo WS URL — demo-fapi ile eşleşen fstream.binance.com (tek URL, flip yok)."""
    if os.getenv("ELITE_DEMO_ONLY_DATA", "1").strip().lower() in ("1", "true", "yes"):
        return [DEMO_WS_PRIMARY]
    prefer = os.getenv("BN_FUT_DEMO_WS_PRIMARY", "binance.com").strip().lower()
    if prefer in ("secondary", "binancefuture", "demo", "binancefuture.com"):
        return [DEMO_WS_SECONDARY, DEMO_WS_PRIMARY]
    return [DEMO_WS_PRIMARY, DEMO_WS_SECONDARY]

# WS handshake kaç kez başarısız olursa "kalıcı engel" say
_WS_GIVEUP_AFTER   = 5       # bu kadar başarısız denemeden sonra yavaşla
_WS_SLOW_INTERVAL  = 60.0    # engel algılandıysa 60 sn'de bir dene
_STALE_KILL_SEC    = 45.0    # bağlı ama mesaj yoksa watchdog öldürür

_lock = threading.Lock()
_prices: dict[str, float] = {}
_event_ms: dict[str, int] = {}
_last_msg_ms: int = 0
_last_recv_ms: int = 0
_connected = False
_reconnects: int = 0
_ws_url_used: str = ""
_ws_blocked: bool = False     # ağ engeli algılandı
_thread: threading.Thread | None = None
_watchdog_thread: threading.Thread | None = None
_stop = threading.Event()
_started = False
_ws_ref: Any = None


# ── REST fiyat enjeksiyonu (ağ engeli varken dışarıdan beslenir) ──────────────

def ingest_rest_prices(prices: dict[str, float]) -> None:
    """REST poller fiyatları buraya yazar; WS gibi davranır."""
    global _last_msg_ms, _last_recv_ms
    now_ms = int(time.time() * 1000)
    with _lock:
        for coin, price in prices.items():
            if price > 0:
                _prices[coin.upper()] = price
                _event_ms[coin.upper()] = now_ms
        _last_msg_ms = now_ms
        _last_recv_ms = now_ms


def is_ws_blocked() -> bool:
    return _ws_blocked


# ── Yardımcılar ───────────────────────────────────────────────────────────────

def _is_demo() -> bool:
    return bool(
        os.getenv("BINANCE_FUTURES_DEMO", "").strip() in ("1", "true")
        or getattr(cfg, "FUTURES_DEMO", False)
        or api_base() == "https://demo-fapi.binance.com"
    )


def ws_base() -> str:
    if _is_demo():
        return _demo_ws_pool()[0]
    if cfg.MODE == "testnet" or (cfg.TESTNET and cfg.API_KEY):
        return TESTNET_WS
    base = api_base()
    if base in ("https://testnet.binancefuture.com", "https://demo-fapi.binance.com"):
        return TESTNET_WS
    return MAIN_WS


def _use_all_mark_stream() -> bool:
    return os.getenv("BN_FUT_MARK_WS_ALL", "").strip().lower() in ("1", "true", "yes")


def _mark_ws_source() -> str:
    """markPrice bazı ağlarda timeout — demo'da bookTicker kararlı."""
    src = os.getenv("BN_FUT_MARK_WS_SOURCE", "auto").strip().lower()
    if src in ("mark", "markprice", "mark_price"):
        return "mark"
    if src in ("bookticker", "book", "book_ticker"):
        return "bookticker"
    if _is_demo() or os.getenv("ELITE_DEMO_ONLY_DATA", "1").strip().lower() in (
        "1",
        "true",
        "yes",
    ):
        return "bookticker"
    return "mark"


def _mark_stream_url(base: str, coins: list[str]) -> str:
    root = base.rstrip("/")
    if _mark_ws_source() == "bookticker":
        return f"{root}/ws/!bookTicker"
    if _use_all_mark_stream():
        return f"{root}/ws/!markPrice@arr@1s"
    return (
        f"{root}/stream?streams="
        f"{'/'.join(f'{c.lower()}usdt@markPrice@1s' for c in coins if c)}"
    )


def _apply_mark(coin: str, price: float, event_ms: int) -> None:
    global _last_msg_ms, _last_recv_ms
    if price <= 0:
        return
    recv_ms = int(time.time() * 1000)
    with _lock:
        _prices[coin.upper()] = price
        _event_ms[coin.upper()] = event_ms
        _last_msg_ms = max(_last_msg_ms, event_ms)
        _last_recv_ms = recv_ms
    try:
        from binance_futures_trader.fast_price_ws import ingest_mid

        ingest_mid(coin, price, price, event_ms)
    except Exception:
        pass


def _watchlist_coins() -> set[str]:
    return {str(c).upper().replace("USDT", "") for c in cfg.WATCHLIST if c}


def _ingest_mark_row(payload: dict) -> None:
    if payload.get("e") not in ("markPriceUpdate", None) and "p" not in payload:
        return
    sym = str(payload.get("s") or "")
    if not sym.endswith("USDT"):
        return
    coin = sym.replace("USDT", "")
    if _use_all_mark_stream():
        allow = _watchlist_coins()
        if allow and coin.upper() not in allow:
            return
    try:
        price = float(payload.get("p") or 0)
        event_ms = int(payload.get("E") or payload.get("T") or time.time() * 1000)
    except (TypeError, ValueError):
        return
    _apply_mark(coin, price, event_ms)


def _ingest_book_row(payload: dict) -> None:
    if str(payload.get("e") or "") != "bookTicker":
        return
    sym = str(payload.get("s") or "")
    if not sym.endswith("USDT"):
        return
    coin = sym.replace("USDT", "")
    allow = _watchlist_coins()
    if allow and coin.upper() not in allow:
        return
    try:
        bid = float(payload.get("b") or 0)
        ask = float(payload.get("a") or 0)
        if bid <= 0 or ask <= 0:
            return
        price = (bid + ask) / 2.0
        event_ms = int(payload.get("E") or payload.get("T") or time.time() * 1000)
    except (TypeError, ValueError):
        return
    _apply_mark(coin, price, event_ms)


def _ingest_payload(payload: dict) -> None:
    if str(payload.get("e") or "") == "bookTicker":
        _ingest_book_row(payload)
    else:
        _ingest_mark_row(payload)


# ── WS callback'leri ─────────────────────────────────────────────────────────

def _on_message(_ws: Any, raw: str) -> None:
    global _connected
    try:
        msg = json.loads(raw)
    except json.JSONDecodeError:
        return
    if isinstance(msg, list):
        for row in msg:
            if isinstance(row, dict):
                _ingest_payload(row)
        _connected = True   # gerçek mesaj geldi
        return
    payload = msg.get("data") if isinstance(msg.get("data"), (dict, list)) else msg
    if isinstance(payload, list):
        for row in payload:
            if isinstance(row, dict):
                _ingest_payload(row)
        _connected = True
        return
    if not isinstance(payload, dict):
        return
    _ingest_payload(payload)
    _connected = True


def _on_open(_ws: Any) -> None:
    # Bağlantı açıldı ama mesaj henüz gelmedi — _connected mesaj gelince set edilir
    global _ws_blocked
    _ws_blocked = False


def _on_close(_ws: Any, *_args: Any) -> None:
    global _connected, _reconnects
    _connected = False
    _reconnects += 1


def _on_error(_ws: Any, err: Any) -> None:
    global _connected
    _connected = False
    msg = str(err or "")
    if "sock" in msg and "NoneType" in msg:
        return
    print(f"  ⚠ mark WS: {msg[:80]}")


def _kill_ws() -> None:
    ref = _ws_ref
    if ref is None:
        return
    try:
        sock = getattr(ref, "sock", None)
        if sock is not None:
            ref.close()
    except Exception:
        pass


# ── Watchdog ─────────────────────────────────────────────────────────────────

def _watchdog_loop() -> None:
    while not _stop.is_set():
        _stop.wait(5)
        if _stop.is_set():
            break
        now_ms = int(time.time() * 1000)
        with _lock:
            last = _last_recv_ms
        # Sadece WS kaynaklı son mesajı izle (REST değil)
        if _connected and last and (now_ms - last) > _STALE_KILL_SEC * 1000:
            _kill_ws()


# ── Ana WS döngüsü ────────────────────────────────────────────────────────────

def _run_loop() -> None:
    global _connected, _reconnects, _ws_url_used, _ws_ref, _ws_blocked
    coins = list(cfg.WATCHLIST)
    fail_count = 0
    demo = _is_demo()
    url_pool = _demo_ws_pool() if demo else [ws_base()]
    url_idx = 0
    url_fail_streak = 0

    while not _stop.is_set():
        if WebSocketApp is None:
            print("  ⚠ mark WS: websocket-client yüklü değil")
            _stop.wait(60)
            return

        base = url_pool[url_idx % len(url_pool)]
        url = _mark_stream_url(base, coins)
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

            # Proxy env temizle
            old_env = dict(os.environ)
            for k in list(os.environ.keys()):
                if k.lower() in {
                    "http_proxy", "https_proxy", "all_proxy",
                    "socks_proxy", "socks5_proxy",
                }:
                    os.environ.pop(k, None)
            try:
                app.run_forever(ping_interval=25, ping_timeout=20, sslopt=ssl_opt)
            finally:
                for k, v in old_env.items():
                    os.environ[k] = v
                _ws_ref = None

        except Exception as exc:
            msg = str(exc)
            if "sock" not in msg or "NoneType" not in msg:
                print(f"  ⚠ mark WS ({base}): {msg[:80]}")

        _connected = False
        _reconnects += 1
        fail_count += 1
        url_fail_streak += 1

        if _stop.is_set():
            break

        # Engel algılama — çok sayıda başarısız deneme
        if fail_count >= _WS_GIVEUP_AFTER and not _ws_blocked:
            _ws_blocked = True
            print(
                f"  ⚠ mark WS: {fail_count} başarısız deneme — "
                f"ağ engeli algılandı, {_WS_SLOW_INTERVAL:.0f}s'de bir retry (demo REST aktif)"
            )

        if demo and len(url_pool) > 1 and url_fail_streak >= 4:
            url_idx += 1
            url_fail_streak = 0

        # Engel varsa yavaş, yoksa hızlı backoff (maks 15s)
        if _ws_blocked:
            wait = _WS_SLOW_INTERVAL
        else:
            base_wait = min(1.0 * (1.4 ** max(0, fail_count - 1)), 15.0)
            wait = base_wait

        print(f"  ↻ mark WS yeniden bağlanıyor ({wait:.0f}s)…")
        _stop.wait(wait)


# ── Başlatma / Durdurma ───────────────────────────────────────────────────────

def ensure_mark_feed_started() -> None:
    global _thread, _watchdog_thread, _started
    try:
        from elite_trader.binance_data_hub import hub_consumer_mode

        if hub_consumer_mode():
            return
    except ImportError:
        pass
    try:
        from binance_futures_trader.async_hub import is_async_hub_enabled

        if is_async_hub_enabled():
            return
    except Exception:
        pass
    if not cfg.MARK_WS_ENABLED:
        return
    if _started and _thread and _thread.is_alive():
        if _watchdog_thread is None or not _watchdog_thread.is_alive():
            _watchdog_thread = threading.Thread(target=_watchdog_loop, name="bn-mark-wd", daemon=True)
            _watchdog_thread.start()
        return
    _stop.clear()
    _thread = threading.Thread(target=_run_loop, name="bn-mark-ws", daemon=True)
    _thread.start()
    _watchdog_thread = threading.Thread(target=_watchdog_loop, name="bn-mark-wd", daemon=True)
    _watchdog_thread.start()
    _started = True


def force_reconnect() -> None:
    global _ws_blocked
    _ws_blocked = False  # Sıfırla — manuel reconnect talebi
    _kill_ws()


def stop_mark_feed() -> None:
    _stop.set()
    global _connected
    _connected = False
    _kill_ws()


# ── Fiyat sorgulama ───────────────────────────────────────────────────────────

def get_mark_prices(*, max_age_sec: float | None = None) -> dict[str, float]:
    """WS veya REST enjeksiyonu ile güncel fiyatlar."""
    age = cfg.MARK_WS_MAX_AGE_SEC if max_age_sec is None else max_age_sec
    now_ms = int(time.time() * 1000)
    out: dict[str, float] = {}
    with _lock:
        keys = list(_prices.keys()) if _use_all_mark_stream() else list(_prices.keys())
        for c in keys:
            px = _prices.get(c)
            ts = _event_ms.get(c, 0)
            if px and px > 0 and (now_ms - ts) <= age * 1000:
                out[c] = px
    return out


def trim_to_coins(coins: set[str]) -> int:
    """WS mark önbelleğini coin kümesiyle sınırla — RAM."""
    if not coins:
        return 0
    allow = {str(c).upper().replace("USDT", "") for c in coins if c}
    removed = 0
    with _lock:
        for k in list(_prices.keys()):
            if str(k).upper() not in allow:
                _prices.pop(k, None)
                _event_ms.pop(k, None)
                removed += 1
    return removed


def get_mark_prices_bulk(*, max_recv_age_sec: float = 90) -> dict[str, float]:
    """Besleme taze ise tüm mark fiyatları — pozisyon tick için (coin başı yaş filtresi yok)."""
    try:
        from binance_futures_trader.async_hub import get_orchestrator, is_async_hub_enabled

        if is_async_hub_enabled():
            orch = get_orchestrator()
            if orch:
                bulk = orch.get_all_marks_if_fresh(max_recv_age_sec=max_recv_age_sec)
                if bulk:
                    return bulk
                bulk = orch.get_all_prices_bulk(max_recv_age_sec=max_recv_age_sec)
                if bulk:
                    return bulk
    except Exception:
        pass
    now_ms = int(time.time() * 1000)
    with _lock:
        if not _prices:
            return {}
        if _last_recv_ms and (now_ms - _last_recv_ms) <= max_recv_age_sec * 1000:
            return {k: float(v) for k, v in _prices.items() if v and float(v) > 0}
    return get_mark_prices(max_age_sec=max_recv_age_sec)


def feed_status() -> dict[str, Any]:
    try:
        from binance_futures_trader.async_hub import get_orchestrator, is_async_hub_enabled

        if is_async_hub_enabled():
            orch = get_orchestrator()
            if orch:
                st = orch.market.status()
                n_coins = int(st.get("mark_coins") or 0) or int(st.get("mid_coins") or 0)
                return {
                    "enabled": True,
                    "connected": bool(st.get("connected")),
                    "ws_blocked": False,
                    "stale": bool(st.get("lag_ms") and st.get("lag_ms") > 5000),
                    "health": "ok" if st.get("ok") else "disconnected",
                    "source": "async_hub",
                    "url": st.get("ws_url"),
                    "coins": n_coins,
                    "last_event_ms": st.get("last_recv_ms"),
                    "last_recv_ms": st.get("last_recv_ms"),
                    "lag_ms": st.get("lag_ms"),
                    "event_lag_ms": st.get("mark_lag_ms"),
                    "reconnects": st.get("reconnects", 0),
                }
    except Exception:
        pass
    now_ms = int(time.time() * 1000)
    with _lock:
        last_recv = _last_recv_ms
        last_ev   = _last_msg_ms
        n         = len(_prices)
        recv_lag  = (now_ms - last_recv) if last_recv else None
        ws_live   = (
            _connected
            and n > 0
            and recv_lag is not None
            and recv_lag < cfg.MARK_WS_MAX_AGE_SEC * 1000
        )
    stale  = recv_lag is not None and recv_lag >= cfg.MARK_WS_MAX_AGE_SEC * 1000
    source = "websocket" if ws_live else ("rest_fallback" if n > 0 else "none")
    if ws_live and _mark_ws_source() == "bookticker":
        source = "websocket_bookticker"
    health = "ok" if (ws_live or (n > 0 and not stale)) else ("stale" if stale else "disconnected")
    return {
        "enabled":        cfg.MARK_WS_ENABLED,
        "connected":      ws_live,
        "ws_blocked":     _ws_blocked,
        "stale":          stale,
        "health":         health,
        "source":         source,
        "feed":           _mark_ws_source(),
        "url":            _ws_url_used,
        "coins":          n,
        "last_event_ms":  last_ev,
        "last_recv_ms":   last_recv,
        "lag_ms":         max(0, recv_lag) if recv_lag is not None else None,
        "event_lag_ms":   max(0, now_ms - last_ev) if last_ev else None,
        "max_age_sec":    cfg.MARK_WS_MAX_AGE_SEC,
        "reconnects":     _reconnects,
        "stale_kill_sec": _STALE_KILL_SEC,
    }
