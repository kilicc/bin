"""Yüksek win rate çıkışı — erken SL yerine TP-RECOVER / kısmi TP / yumuşak SL."""
from __future__ import annotations

import os

from elite_trader.market_guards import can_trigger_sl
from elite_trader.stale_tp import position_release_reason, position_age_seconds


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, str(default)))
    except ValueError:
        return default


def high_winrate_mode() -> bool:
    return os.getenv("ELITE_HIGH_WINRATE_MODE", "0").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def _breakeven_take_usd(stake_usd: float) -> float:
    floor = _env_float("ELITE_RECOVER_BREAKEVEN_USD", 0.28)
    if stake_usd > 0:
        floor = max(floor, stake_usd * _env_float("ELITE_RECOVER_BREAKEVEN_PCT", 0.0012))
    return floor


def decide_position_exit(
    *,
    opened_at: str | None,
    unrealized_usd: float,
    tp_target_usd: float,
    sl_target_usd: float,
    stake_usd: float,
    min_unreal_seen: float,
) -> tuple[bool, str]:
    """
    (should_close, reason)
    High win rate: SL yerine toparlanmayı bekle; kısmi TP ile kazan.
    """
    if not high_winrate_mode():
        return False, ""

    age = position_age_seconds(opened_at)
    unreal = float(unrealized_usd)
    tp_tgt = float(tp_target_usd)
    sl_tgt = float(sl_target_usd)
    dip = float(min_unreal_seen)

    if tp_tgt > 0 and unreal >= tp_tgt and unreal > 0:
        return True, "TP"

    partial_frac = _env_float("ELITE_TP_PARTIAL_FRAC", 0.58)
    min_win = _breakeven_take_usd(stake_usd)
    min_partial_age = _env_float("ELITE_TP_PARTIAL_MIN_AGE_SEC", 75.0)
    if (
        tp_tgt > 0
        and unreal >= tp_tgt * partial_frac
        and unreal >= min_win
        and age >= min_partial_age
    ):
        return True, "TP-PARTIAL"

    rel = position_release_reason(
        opened_at=opened_at,
        unrealized_usd=unreal,
        tp_target_usd=tp_tgt,
        stake_usd=stake_usd,
        min_unreal_seen=dip,
    )
    if rel:
        return True, rel

    if os.getenv("ELITE_SL_TO_TP_RECOVER", "1").strip().lower() in (
        "1",
        "true",
        "yes",
    ):
        loss_seen = -sl_tgt * _env_float("ELITE_RECOVER_DIP_FRAC", 0.55)
        recover_age = _env_float("ELITE_RECOVER_MIN_AGE_SEC", 90.0)
        if dip <= loss_seen and unreal >= min_win and age >= recover_age:
            return True, "TP-RECOVER"

    # SL yok — 2× hedef için yalnızca TP / STALE / TP-RECOVER (acil SL kapalı)
    if os.getenv("ELITE_DISABLE_SL_EXIT", "1").strip().lower() not in (
        "1",
        "true",
        "yes",
    ):
        hard_mult = _env_float("ELITE_SL_HARD_MULT", 8.0)
        if sl_tgt > 0 and unreal <= -sl_tgt * hard_mult:
            if can_trigger_sl(
                opened_at,
                unrealized_usd=unreal,
                sl_target_usd=sl_tgt,
            ):
                return True, "SL-EMERGENCY"
        if sl_tgt > 0 and unreal <= -sl_tgt:
            return True, "SL"

    return False, ""
