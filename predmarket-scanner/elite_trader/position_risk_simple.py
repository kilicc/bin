"""
positionRisk — yalın tek kaynak.

REST yalnızca binance_elite_pro._refresh_positions_cache_only → _positions_cache.
Panel ve MEGA motor UI bu önbelleği kopyalar; ikinci REST (mega refresh) yok.
"""
from __future__ import annotations

import os
import time
from typing import Any


def simple_mode_enabled() -> bool:
    if os.getenv("MEGA_POSITION_RISK_SIMPLE", "").strip().lower() in (
        "1",
        "true",
        "yes",
    ):
        return True
    return os.getenv("MEGA_LEAN_MODE", "").strip().lower() in ("1", "true", "yes")


def elite_positions_snapshot() -> tuple[list[dict[str, Any]], float]:
    """Elite positionRisk önbelleği (ham ep satırları)."""
    try:
        from binance_elite_pro import _exchange_cache_ts, _positions_cache
    except ImportError:
        return [], 0.0
    return list(_positions_cache or []), float(_exchange_cache_ts or 0)


def elite_cache_age_sec() -> float:
    _, ts = elite_positions_snapshot()
    if ts <= 0:
        return 999.0
    return max(0.0, time.time() - ts)


def wake_elite_position_poll() -> None:
    try:
        from binance_elite_pro import _wake_exchange_position_poll

        _wake_exchange_position_poll()
    except Exception:
        pass


def sync_mega_cache_from_elite(*, max_age_sec: float) -> bool:
    """MEGA _mega_positions_cache ← elite _positions_cache (REST yok)."""
    from elite_trader.mega_live import ingest_mega_positions_from_elite_poll

    return ingest_mega_positions_from_elite_poll(max_age_sec=max_age_sec)
