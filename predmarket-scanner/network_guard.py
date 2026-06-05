"""Ağ hatası backoff — hızlı yolda cache; kopuklukta REST/SSL fırtınasını kes."""
from __future__ import annotations

import os
import time

_degraded_until: float = 0.0
_fail_streak: int = 0
_last_fail_at: float = 0.0


def _max_backoff_sec() -> float:
    try:
        return max(4.0, float(os.getenv("ELITE_NETWORK_DEGRADED_MAX_SEC", "12")))
    except ValueError:
        return 12.0


def note_failure(*, kind: str = "network") -> None:
    global _degraded_until, _fail_streak, _last_fail_at
    now = time.time()
    if now - _last_fail_at < 2.0:
        _fail_streak += 1
    else:
        _fail_streak = 1
    _last_fail_at = now
    if kind == "binance_rate_limit":
        try:
            from elite_trader.connection_alerts import ip_ban_until_ms

            until_ms = ip_ban_until_ms()
            if until_ms > 0:
                _degraded_until = max(_degraded_until, until_ms / 1000.0 + 5.0)
                return
        except Exception:
            pass
        _degraded_until = max(_degraded_until, now + min(_max_backoff_sec() * 4, 120.0))
        return
    backoff = min(_max_backoff_sec(), 2.0 ** min(_fail_streak, 4))
    _degraded_until = max(_degraded_until, now + backoff)


def note_success() -> None:
    global _fail_streak
    _fail_streak = 0


def is_degraded() -> bool:
    return time.time() < _degraded_until


def degraded_remaining_sec() -> float:
    return max(0.0, _degraded_until - time.time())


def rest_timeout_sec(default: float) -> float:
    if not is_degraded():
        return default
    return min(default, 1.2)


def skip_rest() -> bool:
    if is_degraded():
        return True
    try:
        from elite_trader.connection_alerts import ip_ban_active

        if ip_ban_active():
            return True
    except Exception:
        pass
    return False


def _paper_only_port() -> bool:
    port = os.getenv("BINANCE_ELITE_PORT", "").strip()
    iid = os.getenv("MEGA_INSTANCE_ID", "").strip()
    return port in ("9005", "9006") or iid in ("9005", "9006")


def binance_outbound_enabled() -> bool:
    """9005/9006 — hiçbir Binance HTTP/WS çıkışı yok (9007 hub tüketir)."""
    if _paper_only_port():
        try:
            from elite_trader.binance_data_hub import hub_consumer_mode

            if hub_consumer_mode():
                return False
        except ImportError:
            return False
    return True


def binance_signed_rest_enabled() -> bool:
    """Imzalı REST — yalnızca 9007 (paper portlarda asla)."""
    if _paper_only_port():
        return False
    return binance_rest_enabled()


def binance_rest_enabled() -> bool:
    """Paper portları REST kapatabilir; canlı yalnızca 9007."""
    if _paper_only_port():
        return False
    flag = os.getenv("ELITE_BINANCE_REST_ENABLED", "1").strip().lower()
    if flag in ("0", "false", "no", "off"):
        return False
    return not skip_rest()
