"""Binance piyasa verisi — yalnızca 9007 yayımlar, 9005/9006 tüketir (dış API yok)."""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Callable

_ROOT = Path(__file__).resolve().parents[1]
_HUB_DIR = _ROOT / "data" / "hub"
_HUB_FEED_PATH = _HUB_DIR / "binance_market_feed.json"
_HUB_FEED_TMP = _HUB_DIR / "binance_market_feed.json.tmp"

_lock = threading.Lock()
_published: dict[str, Any] = {}
_consumer_cache: dict[str, Any] = {}
_consumer_cache_ts: float = 0.0
_publisher_thread: threading.Thread | None = None
_mainnet_thread: threading.Thread | None = None
_stop = threading.Event()
_mainnet_prices: dict[str, dict[str, Any]] = {}
_mainnet_last_ms: int = 0
_mainnet_connected = False
_mainnet_reconnects = 0


def _env_bool(key: str, default: str = "0") -> bool:
    return os.getenv(key, default).strip().lower() in ("1", "true", "yes", "on")


def _paper_port() -> bool:
    port = os.getenv("BINANCE_ELITE_PORT", "").strip()
    iid = os.getenv("MEGA_INSTANCE_ID", "").strip()
    return port in ("9005", "9006") or iid in ("9005", "9006")


def _is_9007() -> bool:
    port = os.getenv("BINANCE_ELITE_PORT", "").strip()
    iid = os.getenv("MEGA_INSTANCE_ID", "").strip()
    return port == "9007" or iid == "9007"


def hub_consumer_mode() -> bool:
    if not _paper_port():
        return False
    return _env_bool("ELITE_BINANCE_DATA_HUB", "1")


def hub_publisher_mode() -> bool:
    if not _is_9007():
        return False
    return _env_bool("ELITE_BINANCE_HUB_PUBLISH", "1")


def hub_base_url() -> str:
    return os.getenv("ELITE_BINANCE_HUB_URL", "http://127.0.0.1:9007").rstrip("/")


def _watchlist_coins() -> list[str]:
    raw = os.getenv("BINANCE_WATCHLIST", "").strip()
    if raw:
        out: list[str] = []
        seen: set[str] = set()
        for part in raw.replace(" ", "").split(","):
            c = part.upper().replace("USDT", "")
            if c and c not in seen:
                seen.add(c)
                out.append(c)
        if out:
            return out
    try:
        from binance_futures_trader import config as bcfg

        out = []
        seen = set()
        for sym in list(getattr(bcfg, "WATCHLIST", []) or []):
            c = str(sym).upper().replace("USDT", "")
            if c and c not in seen:
                seen.add(c)
                out.append(c)
        return out
    except Exception:
        return []


def _mainnet_bookticker_loop() -> None:
    global _mainnet_last_ms, _mainnet_connected, _mainnet_reconnects
    try:
        from websocket import WebSocketApp
    except ImportError:
        return
    from binance_futures_trader.network_ssl import ws_sslopt

    url = "wss://fstream.binance.com/ws/!bookTicker"
    backoff = 1.0
    while not _stop.is_set():
        try:
            def on_message(_ws: Any, raw: str) -> None:
                global _mainnet_last_ms, _mainnet_connected
                try:
                    msg = json.loads(raw)
                except Exception:
                    return
                rows = msg if isinstance(msg, list) else [msg]
                if isinstance(msg, dict) and msg.get("data"):
                    rows = [msg["data"]]
                now_ms = int(time.time() * 1000)
                with _lock:
                    for payload in rows:
                        if not isinstance(payload, dict):
                            continue
                        sym = str(payload.get("s") or "")
                        if not sym.endswith("USDT"):
                            continue
                        coin = sym.replace("USDT", "")
                        bid = float(payload.get("b") or 0)
                        ask = float(payload.get("a") or 0)
                        if bid <= 0 or ask <= 0:
                            continue
                        mid = (bid + ask) / 2.0
                        _mainnet_prices[coin] = {
                            "bid": bid,
                            "ask": ask,
                            "mid": mid,
                            "ts_ms": now_ms,
                        }
                    _mainnet_last_ms = now_ms
                _mainnet_connected = True

            def on_close(*_) -> None:
                global _mainnet_connected
                _mainnet_connected = False

            def on_error(*_) -> None:
                global _mainnet_connected
                _mainnet_connected = False

            app = WebSocketApp(
                url,
                on_message=on_message,
                on_close=on_close,
                on_error=on_error,
            )
            ssl_opt = ws_sslopt()
            old = dict(os.environ)
            for k in list(os.environ.keys()):
                if k.lower() in {"http_proxy", "https_proxy", "all_proxy"}:
                    os.environ.pop(k, None)
            try:
                app.run_forever(ping_interval=20, ping_timeout=15, sslopt=ssl_opt)
            finally:
                for k, v in old.items():
                    os.environ[k] = v
        except Exception:
            pass
        _mainnet_connected = False
        _mainnet_reconnects += 1
        _stop.wait(min(backoff, 10.0))
        backoff = min(backoff * 1.4, 10.0)


def _collect_mainnet_snapshot() -> dict[str, Any]:
    now_ms = int(time.time() * 1000)
    with _lock:
        last = _mainnet_last_ms
        prices = {k: dict(v) for k, v in _mainnet_prices.items()}
    lag = (now_ms - last) if last else None
    marks = {
        k: float(v.get("mid") or 0)
        for k, v in prices.items()
        if float(v.get("mid") or 0) > 0
    }
    ok = bool(marks) and lag is not None and lag < 5000
    return {
        "connected": ok,
        "lag_ms": lag,
        "coins": len(marks),
        "marks": marks,
        "mids": prices,
        "source": "mainnet_bookticker",
        "reconnects": _mainnet_reconnects,
    }


def _collect_publisher_snapshot() -> dict[str, Any]:
    mainnet = _collect_mainnet_snapshot()
    ts_ms = int(time.time() * 1000)
    return {
        "ok": True,
        "ts_ms": ts_ms,
        "publisher": "9007",
        "mainnet": mainnet,
    }


def _write_feed_file(payload: dict[str, Any]) -> None:
    try:
        _HUB_DIR.mkdir(parents=True, exist_ok=True)
        text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        _HUB_FEED_TMP.write_text(text, encoding="utf-8")
        _HUB_FEED_TMP.replace(_HUB_FEED_PATH)
    except Exception:
        pass


def _publisher_loop() -> None:
    iv = max(0.08, float(os.getenv("ELITE_BINANCE_HUB_PUBLISH_SEC", "0.15")))
    while not _stop.is_set():
        snap = _collect_publisher_snapshot()
        with _lock:
            _published.clear()
            _published.update(snap)
        _write_feed_file(snap)
        _stop.wait(iv)


def start_hub_publisher() -> None:
    global _publisher_thread, _mainnet_thread
    if not hub_publisher_mode():
        return
    if _mainnet_thread and _mainnet_thread.is_alive():
        return
    _stop.clear()
    _mainnet_thread = threading.Thread(
        target=_mainnet_bookticker_loop, name="hub-mainnet-bt", daemon=True
    )
    _mainnet_thread.start()
    _publisher_thread = threading.Thread(
        target=_publisher_loop, name="hub-publisher", daemon=True
    )
    _publisher_thread.start()


def stop_hub_publisher() -> None:
    _stop.set()


def publisher_snapshot() -> dict[str, Any]:
    with _lock:
        if _published:
            return dict(_published)
    if _HUB_FEED_PATH.is_file():
        try:
            return json.loads(_HUB_FEED_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return _collect_publisher_snapshot()


def _fetch_http_feed() -> dict[str, Any] | None:
    import urllib.error
    import urllib.request

    url = hub_base_url() + "/api/hub/market"
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=2.5) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None


def fetch_market_feed(*, max_cache_ms: float = 80.0) -> dict[str, Any] | None:
    global _consumer_cache, _consumer_cache_ts
    now = time.time()
    if _consumer_cache and (now - _consumer_cache_ts) * 1000.0 <= max_cache_ms:
        return dict(_consumer_cache)
    snap = _fetch_http_feed()
    if not snap and _HUB_FEED_PATH.is_file():
        try:
            snap = json.loads(_HUB_FEED_PATH.read_text(encoding="utf-8"))
        except Exception:
            snap = None
    if snap:
        _consumer_cache = dict(snap)
        _consumer_cache_ts = now
    return snap


def hub_prices_for_coins(coins: list[str]) -> dict[str, float]:
    snap = fetch_market_feed()
    if not snap:
        return {}
    mainnet = snap.get("mainnet") or {}
    marks: dict[str, float] = dict(mainnet.get("marks") or {})
    if not marks:
        return {}
    out: dict[str, float] = {}
    for coin in coins:
        key = str(coin).upper().replace("USDT", "")
        px = marks.get(key) or marks.get(coin)
        if px and float(px) > 0:
            out[coin] = float(px)
    return out


def hub_feed_status() -> dict[str, Any]:
    if hub_publisher_mode():
        mn = _collect_mainnet_snapshot()
    else:
        snap = fetch_market_feed(max_cache_ms=0.0)
        mn = (snap or {}).get("mainnet") or {}
    lag = mn.get("lag_ms")
    ok = bool(mn.get("connected"))
    return {
        "bookticker": {
            "ok": ok,
            "lag_ms": lag,
            "coins": mn.get("coins", 0),
            "source": "9007_hub",
        },
        "mark_ws": {
            "health": "ok" if ok else "stale",
            "source": "9007_hub_mainnet",
            "lag_ms": lag,
            "coins": mn.get("coins", 0),
        },
        "hub": {
            "consumer": hub_consumer_mode(),
            "publisher": hub_publisher_mode(),
            "url": hub_base_url(),
            "age_ms": int((time.time() - _consumer_cache_ts) * 1000)
            if _consumer_cache_ts
            else None,
        },
    }


def sync_consumer_marks() -> dict[str, float]:
    """9005/9006 — hub mark sözlüğü (boş = 9007 kapalı/stale)."""
    if not hub_consumer_mode():
        return {}
    snap = fetch_market_feed()
    if not snap or not snap.get("ok"):
        return {}
    mainnet = snap.get("mainnet") or {}
    if not mainnet.get("connected"):
        return {}
    marks = mainnet.get("marks") or {}
    return {str(k).upper(): float(v) for k, v in marks.items() if float(v or 0) > 0}
