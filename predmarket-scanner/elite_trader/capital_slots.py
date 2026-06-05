"""Ortak cüzdan slot allocator — tam marjin: $1000 birim; küçük cüzdanda $100–700."""
from __future__ import annotations

import os
from typing import Any


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, str(default)))
    except ValueError:
        return default


def _env_int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, str(default)))
    except ValueError:
        return default


def _env_bool(key: str, default: bool = False) -> bool:
    v = os.getenv(key, "1" if default else "0").strip().lower()
    return v in ("1", "true", "yes")


def _prefix_for_mode(mode_id: str | None) -> str:
    mid = (mode_id or "").strip().lower()
    if mid in ("berserk", "berserk2"):
        return "BERSERK2"
    return "MEGA"


def wallet_full_balance_mode(mode_id: str | None = None) -> bool:
    """Sabit profil slotu yok — serbest marjine göre açılış sayısı."""
    if _prefix_for_mode(mode_id) != "MEGA":
        return False
    return _env_bool("MEGA_WALLET_FULL_BALANCE", True)


def slot_config(mode_id: str | None = None) -> dict[str, float | int]:
    """Env önekleri: MEGA_* veya BERSERK2_*."""
    pfx = _prefix_for_mode(mode_id)
    unit = max(50.0, _env_float(f"{pfx}_SLOT_UNIT_USD", 1000.0))
    if pfx == "MEGA" and not os.getenv("MEGA_SLOT_UNIT_USD"):
        unit = max(50.0, _env_float("MEGA_MIN_SLOT_STAKE_USD", unit))
    small_thr = max(50.0, _env_float(f"{pfx}_SMALL_WALLET_THRESHOLD_USD", unit))
    small_max_default = 700.0 if pfx == "MEGA" else 500.0
    return {
        "slot_unit_usd": unit,
        "small_wallet_threshold_usd": small_thr,
        "small_stake_min_usd": max(10.0, _env_float(f"{pfx}_SMALL_STAKE_MIN_USD", 100.0)),
        "small_stake_max_usd": max(
            10.0, _env_float(f"{pfx}_SMALL_STAKE_MAX_USD", small_max_default)
        ),
        "hard_cap": max(1, _env_int(f"{pfx}_MAX_OPEN_HARD_CAP", 50)),
    }


def effective_max_open(
    deployable_usd: float,
    *,
    profile_cap: int,
    mode_id: str | None = None,
    dynamic: bool = True,
) -> int:
    """Serbest marjine göre slot sayısı (sabit 4+2 yok)."""
    cfg = slot_config(mode_id)
    deploy = max(0.0, float(deployable_usd))
    if deploy <= 0:
        return 0
    unit = float(cfg["slot_unit_usd"])
    small_min = float(cfg["small_stake_min_usd"])
    hard = max(1, int(cfg["hard_cap"]))

    if wallet_full_balance_mode(mode_id):
        if deploy < small_min:
            return 0
        if deploy >= unit:
            return max(1, min(hard, int(deploy // unit)))
        return 1

    prof_cap = max(1, int(profile_cap))
    if not dynamic:
        return prof_cap
    small_thr = float(cfg["small_wallet_threshold_usd"])
    if deploy < small_thr:
        dynamic_n = max(1, int(deploy // small_min))
    else:
        dynamic_n = max(1, int(deploy // unit))
    return max(1, min(hard, max(prof_cap, dynamic_n)))


def plan_stake(
    deployable_usd: float,
    open_count: int,
    *,
    mode_id: str | None = None,
    max_open: int | None = None,
    profile_cap: int = 4,
    is_flash: bool = False,
    flash_min: float = 300.0,
    flash_max: float = 500.0,
) -> float:
    """
    Kalan marjini kalan açılışlara böl.
    Büyük cüzdan (≥$1000 serbest): pozisyon başına $1000.
    Küçük cüzdan: MEGA + flash reversal $100–700 arası.
    """
    deploy = max(0.0, float(deployable_usd))
    cfg = slot_config(mode_id)
    unit = float(cfg["slot_unit_usd"])
    small_min = float(cfg["small_stake_min_usd"])
    small_max = float(cfg["small_stake_max_usd"])
    if max_open is None:
        max_open = effective_max_open(
            deploy,
            profile_cap=max(1, int(profile_cap)),
            mode_id=mode_id,
            dynamic=True,
        )
    remaining = max(0, max_open - int(open_count))
    if remaining <= 0 or deploy <= 0:
        return 0.0
    stake = deploy / remaining

    if wallet_full_balance_mode(mode_id):
        if deploy >= unit:
            min_s, max_s = unit, unit
        else:
            min_s, max_s = small_min, small_max
        if is_flash:
            flash_min = max(min_s, flash_min)
            flash_max = max(flash_min, min(max_s, flash_max))
            stake = max(flash_min, min(flash_max, stake))
        else:
            stake = max(min_s, min(max_s, stake))
        return round(stake, 2)

    small_thr = float(cfg["small_wallet_threshold_usd"])
    if deploy < small_thr:
        min_s = small_min
        max_s = small_max
    else:
        min_s = unit
        max_s = unit
        max_cap = _env_float(f"{_prefix_for_mode(mode_id)}_MAX_SLOT_STAKE_USD", 0)
        if max_cap > 0:
            max_s = min(max_s, max_cap) if max_s > 0 else max_cap
    if is_flash:
        flash_min = max(small_min, flash_min)
        flash_max = max(flash_min, flash_max)
        if _env_bool("MEGA_FLASH_USE_SLOT_SHARE", True) if _prefix_for_mode(mode_id) == "MEGA" else True:
            stake = max(flash_min, min(flash_max, stake))
        else:
            stake = min(flash_max, max(flash_min, deploy * 0.25))
        return round(stake, 2)
    cap = max_s if max_s > 0 else stake
    return round(max(min_s, min(cap, stake)), 2)


def stake_policy_label(deployable_usd: float, mode_id: str | None = None) -> str:
    """Panel / scan özeti için kısa etiket."""
    cfg = slot_config(mode_id)
    unit = float(cfg["slot_unit_usd"])
    if max(0.0, float(deployable_usd)) >= unit:
        return f"${int(unit)}"
    smin = int(cfg["small_stake_min_usd"])
    smax = int(cfg["small_stake_max_usd"])
    return f"${smin}–${smax}"


def slot_allocator_enabled(mode_id: str | None = None) -> bool:
    pfx = _prefix_for_mode(mode_id)
    if pfx == "BERSERK2":
        return _env_bool("BERSERK2_USE_SLOT_ALLOCATOR", False)
    return _env_bool("MEGA_STAKE_USE_AVAILABLE_MARGIN", True) or _env_bool(
        "MEGA_USE_SLOT_ALLOCATOR", True
    )
