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
_consumer_poller_thread: threading.Thread | None = None
_shadow_thread: threading.Thread | None = None
_stop = threading.Event()
_mainnet_prices: dict[str, dict[str, Any]] = {}
_mainnet_last_ms: int = 0
_mainnet_connected = False
_mainnet_reconnects = 0
_shadow_prices: dict[str, dict[str, Any]] = {}
_shadow_last_ms: int = 0
_shadow_connected = False
_last_good_marks: dict[str, float] = {}
_last_good_marks_ts: float = 0.0
_last_good_source: str = ""
_hub_fail_streak: int = 0
_consumer_meta: dict[str, Any] = {}


def _env_bool(key: str, default: str = "0") -> bool:
    return os.getenv(key, default).strip().lower() in ("1", "true", "yes", "on")


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, str(default)))
    except ValueError:
        return default


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


def _hub_max_lag_ms() -> float:
    return max(3000.0, _env_float("ELITE_HUB_MAX_LAG_MS", 18000.0))


def _hub_stale_ok_sec() -> float:
    return max(30.0, _env_float("ELITE_HUB_STALE_OK_SEC", 300.0))


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


def _read_feed_file() -> dict[str, Any] | None:
    if not _HUB_FEED_PATH.is_file():
        return None
    try:
        return json.loads(_HUB_FEED_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None


def _feed_file_age_ms(snap: dict[str, Any] | None) -> int | None:
    if not snap:
        return None
    ts = snap.get("ts_ms")
    if ts is not None:
        try:
            return max(0, int(time.time() * 1000) - int(ts))
        except (TypeError, ValueError):
            pass
    try:
        return max(0, int((time.time() - _HUB_FEED_PATH.stat().st_mtime) * 1000))
    except OSError:
        return None


def _extract_marks_from_snap(
    snap: dict[str, Any] | None,
    *,
    relaxed: bool = True,
) -> tuple[dict[str, float], dict[str, Any]]:
    if not snap:
        return {}, {"source": "none", "coins": 0}
    mainnet = snap.get("mainnet") or {}
    raw = mainnet.get("marks") or {}
    if not raw:
        return {}, {"source": "none", "coins": 0, "lag_ms": mainnet.get("lag_ms")}
    lag = mainnet.get("lag_ms")
    try:
        lag_f = float(lag) if lag is not None else None
    except (TypeError, ValueError):
        lag_f = None
    connected = bool(mainnet.get("connected"))
    max_lag = _hub_max_lag_ms()
    marks = {
        str(k).upper(): float(v)
        for k, v in raw.items()
        if float(v or 0) > 0
    }
    n = len(marks)
    if n < 5:
        return {}, {"source": "empty", "coins": 0, "lag_ms": lag_f}
    strict = connected and (lag_f is None or lag_f <= max_lag)
    relaxed_ok = relaxed and n >= 15 and (lag_f is None or lag_f <= max_lag * 1.5)
    file_age = _feed_file_age_ms(snap)
    file_ok = file_age is not None and file_age <= max_lag * 2
    if strict or relaxed_ok or file_ok:
        src = "9007_hub_http" if snap.get("ok") else "9007_hub_file"
        return marks, {
            "source": src,
            "coins": n,
            "lag_ms": lag_f,
            "connected": connected,
            "file_age_ms": file_age,
        }
    return {}, {
        "source": "stale",
        "coins": n,
        "lag_ms": lag_f,
        "connected": connected,
        "file_age_ms": file_age,
    }


def _remember_good_marks(marks: dict[str, float], meta: dict[str, Any]) -> None:
    global _last_good_marks, _last_good_marks_ts, _last_good_source, _hub_fail_streak, _consumer_meta
    if len(marks) < 5:
        return
    _last_good_marks = dict(marks)
    _last_good_marks_ts = time.time()
    _last_good_source = str(meta.get("source") or "hub")
    _hub_fail_streak = 0
    _consumer_meta = dict(meta)


def _shadow_marks() -> dict[str, float]:
    now_ms = int(time.time() * 1000)
    with _lock:
        prices = dict(_shadow_prices)
        last = _shadow_last_ms
    if not prices:
        return {}
    lag = (now_ms - last) if last else None
    if lag is not None and lag > _hub_max_lag_ms() * 2:
        return {}
    return {
        k: float(v.get("mid") or 0)
        for k, v in prices.items()
        if float(v.get("mid") or 0) > 0
    }


def _consumer_shadow_ws_loop() -> None:
    global _shadow_last_ms, _shadow_connected
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
                global _shadow_last_ms, _shadow_connected
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
                        _shadow_prices[coin] = {
                            "bid": bid,
                            "ask": ask,
                            "mid": (bid + ask) / 2.0,
                            "ts_ms": now_ms,
                        }
                    _shadow_last_ms = now_ms
                _shadow_connected = True

            def on_close(*_) -> None:
                global _shadow_connected
                _shadow_connected = False

            def on_error(*_) -> None:
                global _shadow_connected
                _shadow_connected = False

            app = WebSocketApp(
                url,
                on_message=on_message,
                on_close=on_close,
                on_error=on_error,
            )
            ssl_opt = ws_sslopt()
            app.run_forever(ping_interval=20, ping_timeout=15, sslopt=ssl_opt)
        except Exception:
            pass
        _shadow_connected = False
        _stop.wait(min(backoff, 10.0))
        backoff = min(backoff * 1.4, 10.0)


def _ensure_consumer_shadow_ws() -> None:
    global _shadow_thread
    if not hub_consumer_mode() or not _env_bool("ELITE_HUB_SHADOW_WS", "1"):
        return
    if _shadow_thread and _shadow_thread.is_alive():
        return
    _shadow_thread = threading.Thread(
        target=_consumer_shadow_ws_loop,
        name="hub-consumer-shadow-bt",
        daemon=True,
    )
    _shadow_thread.start()


def _fetch_http_feed() -> dict[str, Any] | None:
    import urllib.error
    import urllib.request

    url = hub_base_url() + "/api/hub/market"
    timeout = max(0.8, min(4.0, _env_float("ELITE_HUB_HTTP_TIMEOUT_SEC", 1.8)))
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None


def fetch_market_feed(*, max_cache_ms: float = 80.0) -> dict[str, Any] | None:
    global _consumer_cache, _consumer_cache_ts
    now = time.time()
    if _consumer_cache and (now - _consumer_cache_ts) * 1000.0 <= max_cache_ms:
        return dict(_consumer_cache)
    snap = _read_feed_file()
    file_age = _feed_file_age_ms(snap)
    need_http = (
        not snap
        or file_age is None
        or file_age > max(500.0, max_cache_ms * 2)
    )
    if need_http:
        http_snap = _fetch_http_feed()
        if http_snap:
            snap = http_snap
    if not snap:
        snap = _consumer_cache or None
    if snap:
        _consumer_cache = dict(snap)
        _consumer_cache_ts = now
    return snap


def consumer_marks_bulk(*, allow_stale: bool = True) -> dict[str, float]:
    """
    9005/9006 sıcak yol — disk → HTTP → bellek → son-iyi → shadow WS.
    Asla boş dönme eğilimi (performans ayarı değişmeden).
    """
    global _hub_fail_streak, _consumer_meta

    # 1) Paylaşımlı disk (9007 yazar, ~150ms) — HTTP'den hızlı
    file_snap = _read_feed_file()
    marks, meta = _extract_marks_from_snap(file_snap, relaxed=True)
    if len(marks) >= 15:
        _remember_good_marks(marks, {**meta, "source": "9007_hub_file"})
        return marks

    # 2) HTTP (taze)
    http_snap = _fetch_http_feed()
    if http_snap:
        with _lock:
            _consumer_cache.clear()
            _consumer_cache.update(http_snap)
        global _consumer_cache_ts
        _consumer_cache_ts = time.time()
        marks, meta = _extract_marks_from_snap(http_snap, relaxed=True)
        if len(marks) >= 15:
            _remember_good_marks(marks, meta)
            return marks

    # 3) HTTP/disk snap gevşek — connected bayrak takılmasın
    for snap in (http_snap, file_snap, _consumer_cache):
        if not snap:
            continue
        mainnet = snap.get("mainnet") or {}
        raw = mainnet.get("marks") or {}
        marks = {
            str(k).upper(): float(v)
            for k, v in raw.items()
            if float(v or 0) > 0
        }
        if len(marks) >= 15:
            _remember_good_marks(
                marks,
                {"source": "9007_hub_relaxed", "coins": len(marks)},
            )
            return marks

    _hub_fail_streak += 1
    if _hub_fail_streak >= 25:
        _ensure_consumer_shadow_ws()

    # 4) Son bilinen iyi snapshot
    if allow_stale and _last_good_marks:
        age = time.time() - float(_last_good_marks_ts or 0)
        if age <= _hub_stale_ok_sec():
            _consumer_meta = {
                "source": f"{_last_good_source}_stale",
                "coins": len(_last_good_marks),
                "stale_age_sec": round(age, 1),
            }
            return dict(_last_good_marks)

    # 5) Acil shadow WS (yalnızca hub uzun süre ölüyse)
    shadow = _shadow_marks()
    if len(shadow) >= 15:
        _remember_good_marks(shadow, {"source": "consumer_shadow_ws", "coins": len(shadow)})
        return shadow

    return dict(_last_good_marks) if _last_good_marks else {}


def sync_consumer_marks() -> dict[str, float]:
    """Geriye uyumluluk — consumer_marks_bulk()."""
    if not hub_consumer_mode():
        return {}
    return consumer_marks_bulk(allow_stale=True)


def consumer_resilience_status() -> dict[str, Any]:
    marks = consumer_marks_bulk(allow_stale=True)
    now = time.time()
    age = (now - _last_good_marks_ts) if _last_good_marks_ts else None
    return {
        "ok": len(marks) >= 15,
        "coins": len(marks),
        "source": _consumer_meta.get("source") or _last_good_source or "none",
        "last_good_age_sec": round(age, 1) if age is not None else None,
        "fail_streak": _hub_fail_streak,
        "shadow_ws": bool(_shadow_thread and _shadow_thread.is_alive()),
        "file_exists": _HUB_FEED_PATH.is_file(),
        "file_age_ms": _feed_file_age_ms(_read_feed_file()),
    }


def _consumer_poller_loop() -> None:
    iv = max(0.06, min(0.25, _env_float("ELITE_HUB_CONSUMER_POLL_SEC", 0.12)))
    while not _stop.is_set():
        try:
            consumer_marks_bulk(allow_stale=True)
        except Exception:
            pass
        _stop.wait(iv)


def start_hub_consumer_resilience() -> None:
    """9005/9006 — arka plan hub poll + disk preload (tarama kopmasın)."""
    global _consumer_poller_thread
    if not hub_consumer_mode():
        return
    try:
        marks = consumer_marks_bulk(allow_stale=False)
        if marks:
            print(f"  📂 Hub preload: {len(marks)} mark ({_last_good_source or 'disk'})")
    except Exception:
        pass
    if _consumer_poller_thread and _consumer_poller_thread.is_alive():
        return
    _consumer_poller_thread = threading.Thread(
        target=_consumer_poller_loop,
        name="hub-consumer-poller",
        daemon=True,
    )
    _consumer_poller_thread.start()


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


def hub_prices_for_coins(coins: list[str]) -> dict[str, float]:
    bulk = consumer_marks_bulk(allow_stale=True) if hub_consumer_mode() else {}
    if not bulk:
        snap = fetch_market_feed()
        if not snap:
            return {}
        mainnet = snap.get("mainnet") or {}
        bulk = dict(mainnet.get("marks") or {})
    out: dict[str, float] = {}
    for coin in coins:
        key = str(coin).upper().replace("USDT", "")
        px = bulk.get(key) or bulk.get(coin)
        if px and float(px) > 0:
            out[coin] = float(px)
    return out


def hub_feed_status() -> dict[str, Any]:
    if hub_publisher_mode():
        mn = _collect_mainnet_snapshot()
    elif hub_consumer_mode():
        rs = consumer_resilience_status()
        marks = consumer_marks_bulk(allow_stale=True)
        lag = rs.get("file_age_ms")
        if lag is None and _consumer_meta.get("lag_ms") is not None:
            lag = _consumer_meta.get("lag_ms")
        ok = len(marks) >= 15
        mn = {
            "connected": ok,
            "lag_ms": lag,
            "coins": len(marks),
            "marks": marks,
            "source": rs.get("source"),
        }
    else:
        snap = fetch_market_feed(max_cache_ms=0.0)
        mn = (snap or {}).get("mainnet") or {}
    lag = mn.get("lag_ms")
    ok = bool(mn.get("connected")) or int(mn.get("coins") or 0) >= 15
    mark_ws: dict[str, Any] = {
        "health": "ok" if ok else "stale",
        "source": mn.get("source") or "9007_hub_mainnet",
        "lag_ms": lag,
        "coins": mn.get("coins", 0),
    }
    try:
        from elite_trader.mega_async_hub import mega_hub_mark_ws_status

        mh = mega_hub_mark_ws_status()
        if mh and hub_publisher_mode():
            mark_ws = mh
    except ImportError:
        pass
    return {
        "bookticker": {
            "ok": ok,
            "lag_ms": lag,
            "coins": mn.get("coins", 0),
            "source": "9007_hub",
        },
        "mark_ws": mark_ws,
        "hub": {
            "consumer": hub_consumer_mode(),
            "publisher": hub_publisher_mode(),
            "url": hub_base_url(),
            "age_ms": int((time.time() - _consumer_cache_ts) * 1000)
            if _consumer_cache_ts
            else None,
            "resilience": consumer_resilience_status() if hub_consumer_mode() else None,
        },
    }
