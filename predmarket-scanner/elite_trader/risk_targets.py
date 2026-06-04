"""TP/SL hedefleri — env (ELITE_*_STAKE_PCT, ELITE_TP_TRIGGER_FRAC)."""
from __future__ import annotations

import os


def _f(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, str(default)))
    except ValueError:
        return default


def tp_stake_pct() -> float:
    return _f("ELITE_TP_STAKE_PCT", 0.007)


def sl_stake_pct() -> float:
    return _f("ELITE_SL_STAKE_PCT", 0.025)


def tp_trigger_frac() -> float:
    return _f("ELITE_TP_TRIGGER_FRAC", 0.85)
