"""Optimizasyon sınırları — otomatik ayar taşmasını engeller."""
from __future__ import annotations

from typing import Any

OPT_BOUNDS: dict[str, tuple[float, float]] = {
    "min_edge": (0.04, 0.45),
    "min_formula_score": (0.45, 0.75),
    "evrim_min_total_score": (45.0, 75.0),
    "tp_stake_pct": (0.0018, 0.025),
    "sl_stake_pct": (0.0010, 0.0080),
    "active_capital_pct": (0.20, 0.95),
    "max_open": (3.0, 20.0),
    "max_open_per_symbol": (1.0, 3.0),
    "daily_dd_warn_pct": (0.0, 0.08),
    "daily_dd_halt_pct": (0.0, 0.12),
    "fee_gross_recovery": (0.60, 0.85),
}


def clamp_param(key: str, value: float) -> float:
    lo, hi = OPT_BOUNDS.get(key, (value, value))
    return max(lo, min(hi, float(value)))


def clamp_profile_patch(patch: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in patch.items():
        if k in OPT_BOUNDS and isinstance(v, (int, float)):
            out[k] = clamp_param(k, float(v))
        else:
            out[k] = v
    return out
