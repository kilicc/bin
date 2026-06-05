"""BERSERK2 / MEGA — BTC 1m rejim (sık güncelleme, hacim/kitap, dinamik faz)."""
from __future__ import annotations

import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from typing import Any

_lock = threading.Lock()
_ctx: dict[str, Any] = {
    "btc_regime": "unknown",
    "btc_regime_base": "unknown",
    "btc_24h_change": None,
    "btc_price": None,
    "updated_at": 0.0,
    "regime_updated_at": 0.0,
    "btc_1m_wick_drop_pct": None,
    "btc_1m_wick_pump_pct": None,
    "btc_vol_ratio": None,
    "btc_vol_spike": False,
    "btc_book_imbalance": None,
    "klines_interval": "1m",
}
_btc_refresh_inflight = False
_klines_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="btc-klines")
_watcher_stop = threading.Event()
_watcher_thread: threading.Thread | None = None
_watcher_client: Any | None = None
_last_klines: list[dict[str, Any]] = []


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, str(default)))
    except ValueError:
        return default


def _env_bool(key: str, default: bool = True) -> bool:
    v = os.getenv(key, "1" if default else "0").strip().lower()
    return v in ("1", "true", "yes")


def btc_kline_interval() -> str:
    return os.getenv("MEGA_BTC_KLINE_INTERVAL", "1m").strip() or "1m"


def btc_kline_limit() -> int:
    return max(20, min(120, int(_env_float("MEGA_BTC_KLINE_LIMIT", 60))))


def btc_refresh_min_sec() -> float:
    return max(0.5, _env_float("MEGA_BTC_REFRESH_SEC", 1.0))


def btc_klines_timeout_sec() -> float:
    return max(0.6, min(4.0, _env_float("MEGA_BTC_KLINES_TIMEOUT_SEC", 1.2)))


def btc_watcher_fast_sec() -> float:
    return max(0.2, _env_float("MEGA_BTC_FAST_TICK_SEC", 0.3))


def _ema(values: list[float], period: int) -> float:
    if not values:
        return 0.0
    k = 2.0 / (period + 1)
    ema = values[0]
    for v in values[1:]:
        ema = v * k + ema * (1 - k)
    return ema


def _atr_pct(klines: list[dict[str, Any]]) -> float:
    if len(klines) < 3:
        return 0.0
    trs: list[float] = []
    for i in range(1, len(klines)):
        h = float(klines[i].get("h") or 0)
        l = float(klines[i].get("l") or 0)
        pc = float(klines[i - 1].get("c") or 0)
        tr = max(h - l, abs(h - pc), abs(l - pc))
        if pc > 0:
            trs.append(tr / pc * 100.0)
    return sum(trs) / len(trs) if trs else 0.0


def _regime_from_klines(kl: list[dict[str, Any]], *, sensitive: bool = False) -> str:
    min_bars = 12 if sensitive else 15
    if len(kl) < min_bars:
        return "unknown"
    closes = [float(x.get("c") or 0) for x in kl]
    if not closes or closes[-1] <= 0:
        return "unknown"
    be9 = _ema(closes[-20:], 9)
    be21 = _ema(closes[-22:], 21)
    up_mult = 1.00015 if sensitive else 1.0003
    dn_mult = 0.99985 if sensitive else 0.9997
    if be9 > be21 * up_mult:
        trend = "up"
    elif be9 < be21 * dn_mult:
        trend = "down"
    else:
        trend = "flat"
    chop_thr = 0.045 if sensitive else 0.06
    if _atr_pct(kl) < chop_thr:
        return "chop"
    if trend == "flat":
        return "mixed"
    return f"trend_{trend}"


def _micro_regime_overlay(kl: list[dict[str, Any]]) -> str | None:
    """Son 1m mumlar — ani şelalede rejimi hızlı çevir."""
    if not _env_bool("MEGA_BTC_REGIME_DYNAMIC", True) or len(kl) < 5:
        return None
    n = max(3, min(8, int(_env_float("MEGA_BTC_REGIME_MICRO_BARS", 5))))
    closes = [float(k.get("c") or 0) for k in kl[-n:] if float(k.get("c") or 0) > 0]
    if len(closes) < 3:
        return None
    ch = (closes[-1] - closes[0]) / closes[0] * 100.0
    dn = _env_float("MEGA_BTC_REGIME_MICRO_DOWN_PCT", 0.08)
    up = _env_float("MEGA_BTC_REGIME_MICRO_UP_PCT", 0.08)
    if ch <= -dn:
        return "trend_down"
    if ch >= up:
        return "trend_up"
    return None


def _wick_metrics_1m(kl: list[dict[str, Any]]) -> dict[str, Any]:
    """Son tamamlanan mumlar — tepe/dip wick %."""
    out: dict[str, Any] = {
        "btc_1m_wick_drop_pct": None,
        "btc_1m_wick_pump_pct": None,
        "btc_vol_ratio": None,
        "btc_vol_spike": False,
    }
    if len(kl) < 8:
        return out
    completed = kl[:-1] if len(kl) > 1 else kl
    window = completed[-max(8, min(20, int(_env_float("MEGA_BTC_WICK_LOOKBACK", 12)))) :]
    highs = [float(k.get("h") or 0) for k in window]
    lows = [float(k.get("l") or 0) for k in window]
    if not highs or not lows:
        return out
    peak = max(highs)
    low = min(lows)
    if peak > 0 and low < peak:
        out["btc_1m_wick_drop_pct"] = round((peak - low) / peak * 100.0, 4)
    if low > 0 and peak > low:
        out["btc_1m_wick_pump_pct"] = round((peak - low) / low * 100.0, 4)
    vols = [float(k.get("v") or 0) for k in completed[-8:-1]]
    last_v = float(completed[-1].get("v") or 0)
    if vols and last_v > 0:
        avg = sum(vols) / len(vols)
        if avg > 0:
            ratio = last_v / avg
            out["btc_vol_ratio"] = round(ratio, 3)
            out["btc_vol_spike"] = ratio >= _env_float("MEGA_BTC_VOL_SPIKE_RATIO", 1.55)
    return out


def _btc_book_imbalance() -> float | None:
    try:
        from elite_trader.exchange_fill_truth import _book_ticker

        book = _book_ticker("BTC", max_age_ms=280.0)
        if not book:
            return None
        bid = float(book.get("bid") or 0)
        ask = float(book.get("ask") or 0)
        if bid <= 0 or ask <= 0:
            return None
        mid = (bid + ask) / 2.0
        if mid <= 0:
            return None
        return round((bid - ask) / mid * 10000.0, 2)
    except Exception:
        return None


def get_btc_klines_cached() -> list[dict[str, Any]]:
    with _lock:
        return list(_last_klines)


def _fetch_btc_klines(binance_client: Any) -> list[dict[str, Any]]:
    fut = _klines_executor.submit(
        binance_client.klines,
        "BTC",
        btc_kline_interval(),
        btc_kline_limit(),
    )
    return fut.result(timeout=btc_klines_timeout_sec()) or []


def _hub_btc_24h() -> float | None:
    try:
        from elite_trader.market_intelligence_hub import get_hub

        hub = get_hub()
        snap = hub.snapshot() if hub else {}
        ch = snap.get("btc_24h_change")
        return float(ch) if ch is not None else None
    except Exception:
        return None


def _cached_btc_price() -> float | None:
    for sym in ("BTCUSDT", "BTC"):
        try:
            import binance_elite_pro as bep

            with bep._price_cache_lock:
                px = float(bep._price_cache.get(sym) or 0)
            if px > 0:
                return px
        except Exception:
            pass
    try:
        import binance_elite_pro as bep

        hist = getattr(bep, "price_history", {}) or {}
        rows = hist.get("BTCUSDT") or hist.get("BTC") or []
        if rows:
            px = float(rows[-1].get("price") or 0)
            if px > 0:
                return px
    except Exception:
        pass
    return None


def _record_btc_tick(price: float) -> None:
    """İzleyici — BTC tick geçmişi (şelale için saniye ölçeği)."""
    if price <= 0:
        return
    try:
        from elite_trader.market_intelligence_hub import get_hub

        import binance_elite_pro as bep

        get_hub().record_tick("BTCUSDT", price, bep.price_history)
    except Exception:
        pass


def patch_btc_context_fast() -> dict[str, Any]:
    """Hub + fiyat + kitap — API klines yok."""
    global _ctx
    now = time.time()
    btc_24h = _hub_btc_24h()
    btc_price = _cached_btc_price()
    if btc_price and btc_price > 0:
        _record_btc_tick(float(btc_price))
    try:
        from elite_trader.btc_macro_feed import patch_btc_macro_fast

        patch_btc_macro_fast()
    except Exception:
        pass
    book_imb = _btc_book_imbalance()
    with _lock:
        cur = dict(_ctx)
        if btc_24h is not None:
            cur["btc_24h_change"] = btc_24h
        if btc_price is not None and btc_price > 0:
            cur["btc_price"] = btc_price
        if book_imb is not None:
            cur["btc_book_imbalance"] = book_imb
        if cur != _ctx:
            cur["updated_at"] = now
            _ctx = cur
        return dict(_ctx)


def refresh_btc_context(binance_client: Any | None = None) -> dict[str, Any]:
    """1m klines + dinamik rejim + hacim wick."""
    global _ctx, _last_klines
    now = time.time()
    with _lock:
        last = float(_ctx.get("regime_updated_at") or _ctx.get("updated_at") or 0)
        if (now - last) < btc_refresh_min_sec():
            return dict(_ctx)

    base = patch_btc_context_fast()
    regime_base = str(base.get("btc_regime_base") or base.get("btc_regime") or "unknown")
    regime = regime_base
    btc_24h = base.get("btc_24h_change")
    btc_price = base.get("btc_price")
    book_imb = base.get("btc_book_imbalance")
    wick: dict[str, Any] = {}

    if binance_client is not None:
        try:
            kl = _fetch_btc_klines(binance_client)
            if kl:
                _last_klines = kl
                sensitive = _env_bool("MEGA_BTC_REGIME_SENSITIVE", True)
                regime_base = _regime_from_klines(kl, sensitive=sensitive)
                overlay = _micro_regime_overlay(kl)
                regime = overlay or regime_base
                btc_price = float(kl[-1].get("c") or 0) or btc_price
                wick = _wick_metrics_1m(kl)
        except (FuturesTimeoutError, Exception):
            pass

    out = {
        "btc_regime": regime,
        "btc_regime_base": regime_base,
        "btc_24h_change": btc_24h,
        "btc_price": btc_price,
        "btc_book_imbalance": book_imb,
        "klines_interval": btc_kline_interval(),
        "updated_at": now,
        "regime_updated_at": now if regime != "unknown" else float(
            _ctx.get("regime_updated_at") or 0
        ),
        **wick,
    }
    try:
        from elite_trader.btc_macro_feed import refresh_btc_macro

        refresh_btc_macro(binance_client, force=False)
    except Exception:
        pass
    with _lock:
        _ctx = out
    return dict(out)


def schedule_btc_refresh(binance_client: Any | None) -> None:
    global _btc_refresh_inflight
    with _lock:
        if _btc_refresh_inflight:
            return
        last = float(_ctx.get("regime_updated_at") or _ctx.get("updated_at") or 0)
        if (time.time() - last) < btc_refresh_min_sec():
            return
        _btc_refresh_inflight = True

    def _run() -> None:
        global _btc_refresh_inflight
        try:
            refresh_btc_context(binance_client)
        finally:
            with _lock:
                _btc_refresh_inflight = False

    threading.Thread(target=_run, name="berserk2-btc", daemon=True).start()


def _resolve_watcher_client() -> Any | None:
    if _watcher_client is not None:
        return _watcher_client
    try:
        from elite_trader.mega_live import get_mega_client

        return get_mega_client()
    except Exception:
        return None


def _btc_watcher_loop() -> None:
    next_klines = 0.0
    while not _watcher_stop.is_set():
        try:
            patch_btc_context_fast()
        except Exception:
            pass
        now = time.time()
        if now >= next_klines:
            client = _resolve_watcher_client()
            if client is not None and not getattr(client, "paper", False):
                schedule_btc_refresh(client)
            next_klines = now + btc_refresh_min_sec()
        _watcher_stop.wait(timeout=btc_watcher_fast_sec())


def start_btc_regime_watcher(binance_client: Any | None = None) -> None:
    global _watcher_thread, _watcher_client
    if not _env_bool("MEGA_BTC_WATCHER", True):
        return
    _watcher_client = binance_client
    if _watcher_thread and _watcher_thread.is_alive():
        return
    _watcher_stop.clear()
    _watcher_thread = threading.Thread(
        target=_btc_watcher_loop, name="mega-btc-regime", daemon=True
    )
    _watcher_thread.start()
    if binance_client is not None:
        schedule_btc_refresh(binance_client)
        try:
            from elite_trader.btc_macro_feed import refresh_btc_macro

            refresh_btc_macro(binance_client, force=True)
        except Exception:
            pass


def stop_btc_regime_watcher() -> None:
    _watcher_stop.set()
    global _watcher_thread
    th = _watcher_thread
    if th and th.is_alive():
        th.join(timeout=2.0)
    _watcher_thread = None


def get_btc_context() -> dict[str, Any]:
    with _lock:
        return dict(_ctx)
