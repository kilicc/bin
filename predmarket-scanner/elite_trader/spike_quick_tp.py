"""Spike / hızlı scalp — ücreti karşılayan kısa kârı erken kilitle (tam TP beklemeden)."""
from __future__ import annotations

import os

from elite_trader.stale_tp import position_age_seconds
from elite_trader.symbol_quality import round_trip_fee_usd


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, str(default)))
    except ValueError:
        return default


def enabled() -> bool:
    return os.getenv("ELITE_SPIKE_QUICK_TP_ENABLED", "0").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def min_age_seconds() -> float:
    return _env_float("ELITE_SPIKE_QUICK_TP_MIN_AGE_SEC", 40.0)


def _fee_floor_usd(stake_usd: float) -> float:
    mult = _env_float("ELITE_SPIKE_QUICK_TP_FEE_MULT", 1.08)
    return round_trip_fee_usd(stake_usd, 3) * mult


def should_close_spike_quick(
    *,
    opened_at: str | None,
    unrealized_usd: float,
    tp_target_usd: float,
    stake_usd: float,
    max_unreal_seen: float = 0.0,
) -> bool:
    """
    Tam TP'ye gitmeden, ücret+marj sonrası kısa yeşil pencerede çık.
    max_unreal_seen: pozisyon boyunca en yüksek unrealized (spike tepe).
    """
    if not enabled() or tp_target_usd <= 0 or stake_usd <= 0:
        return False
    if position_age_seconds(opened_at) < min_age_seconds():
        return False

    floor = _fee_floor_usd(stake_usd)
    max_frac = _env_float("ELITE_SPIKE_QUICK_TP_MAX_FRAC", 0.72)
    quick_tgt = max(floor, tp_target_usd * max_frac)

    if unrealized_usd < floor:
        return False
    # Hâlâ tam TP'ye yakınsa tam TP beklesin
    if unrealized_usd >= tp_target_usd * 0.92:
        return False
    # Spike: bir ara anlamlı yeşil gördü, şimdi hâlâ ücret üstü ama tam TP değil
    peak = max(max_unreal_seen, unrealized_usd)
    if peak < quick_tgt * 0.85:
        return False
    if unrealized_usd >= floor and unrealized_usd <= quick_tgt * 1.05:
        return True
    # Geri çekilme: tepeden %15 düşüş ama hâlâ fee üstü
    if peak >= quick_tgt and unrealized_usd >= floor and unrealized_usd < peak * 0.85:
        return True
    return False
