"""
5 modlu paralel evren — kimlik, rol, erişim kuralları.
"""
from __future__ import annotations

import os
from typing import Any

MODE_IDS: tuple[str, ...] = (
    "evrim",
    "berserk",
    "berserk2",
    "hunter",
    "chop_master",
    "sentinel",
    "mega",
)

BERSERK_FAMILY_IDS: frozenset[str] = frozenset({"berserk", "berserk2"})

DEFAULT_ACTIVE_FUTURES_MODE = os.getenv("ELITE_DEFAULT_EXECUTION_MODE", "berserk2")
DEFAULT_VIEW_MODE = os.getenv("ELITE_DEFAULT_VIEW_MODE", DEFAULT_ACTIVE_FUTURES_MODE)
DEFAULT_STARTING_BALANCE = 5000.0

# Eski ID → yeni ID (geçiş)
LEGACY_ALIASES: dict[str, str] = {
    "live_9005": "sentinel",
    "evren_evrim": "evrim",
    "evren_simsek": "berserk",
    "evren_avci": "hunter",
    "evren_kalkan": "chop_master",
    "spike_fast": "berserk",
    "spike_scalp": "berserk",
    "avci": "hunter",
    "kalkan": "chop_master",
    "simsek": "berserk",
    "evrim_2x": "evrim",
    "2x_evrim": "evrim",
    "ana_hat": "sentinel",
}

MODE_META: dict[str, dict[str, Any]] = {
    "evrim": {
        "display_name": "EVRIM",
        "label": "Evrim",
        "short_label": "Evrim",
        "role": "v2_live_meta_adaptive_brain",
        "trading_style": "adaptive_multi_mode_meta_trader",
        "learning_access": "all_modes_summary_read",
        "can_trade_live": True,
        "default_paper": False,
        "character": "V2 meta-adaptive live brain",
    },
    "berserk": {
        "display_name": "BERSERK",
        "label": "Berserk",
        "short_label": "Berserk",
        "role": "v2_micro_momentum_velocity_lab",
        "trading_style": "ultra_fast_micro_scalp",
        "learning_access": "own_data_only",
        "can_trade_live": True,
        "default_paper": True,
        "character": "Micro-scalp veri canavarı — koşullu live",
    },
    "berserk2": {
        "display_name": "BERSERK2",
        "label": "Berserk2",
        "short_label": "Brk2",
        "role": "v2_top10_mover_btc_aware_scalp",
        "trading_style": "focused_top10_micro_scalp",
        "learning_access": "own_data_only",
        "can_trade_live": True,
        "default_paper": True,
        "character": "Günün top-10 hareketli coin + BTC rejim — yoğun TP scalp",
    },
    "hunter": {
        "display_name": "HUNTER",
        "label": "Hunter",
        "short_label": "Hunter",
        "role": "v2_breakout_spike_liquidation_hunter",
        "trading_style": "explosive_move_capture",
        "learning_access": "own_data_only",
        "can_trade_live": True,
        "default_paper": True,
        "character": "Büyük fırsat avcısı",
    },
    "chop_master": {
        "display_name": "CHOP_MASTER",
        "label": "Chop Master",
        "short_label": "Chop",
        "role": "v2_chop_mean_reversion_lab",
        "trading_style": "range_reversal_micro_scalp",
        "learning_access": "own_data_only",
        "can_trade_live": True,
        "default_paper": True,
        "character": "Chop V2 mean reversion lab",
    },
    "sentinel": {
        "display_name": "SENTINEL",
        "label": "Sentinel",
        "short_label": "Sentinel",
        "role": "v2_quality_trend_risk_benchmark",
        "trading_style": "selective_trend_following",
        "learning_access": "own_data_only",
        "can_trade_live": True,
        "default_paper": True,
        "character": "V2 kalite / risk / benchmark radar",
    },
    "mega": {
        "display_name": "MEGA",
        "label": "Mega",
        "short_label": "Mega",
        "role": "v2_big_scalp_paper_lab",
        "trading_style": "large_scalp_no_sl_paper",
        "learning_access": "own_data_only",
        "can_trade_live": False,
        "default_paper": True,
        "character": "Büyük scalp paper — SL yok, $400–$1000 stake",
    },
}

PAPER_LAB_IDS: tuple[str, ...] = (
    "berserk",
    "berserk2",
    "hunter",
    "chop_master",
    "sentinel",
    "mega",
)


def is_berserk_family(mode_id: str | None) -> bool:
    return resolve_mode_id(mode_id) in BERSERK_FAMILY_IDS


def resolve_mode_id(mode_id: str | None) -> str:
    raw = str(mode_id or "").strip()
    if not raw:
        return DEFAULT_ACTIVE_FUTURES_MODE
    low = raw.lower()
    if low in MODE_IDS:
        return low
    return LEGACY_ALIASES.get(raw, LEGACY_ALIASES.get(low, raw))


def is_valid_mode(mode_id: str) -> bool:
    return resolve_mode_id(mode_id) in MODE_IDS


def mode_meta(mode_id: str) -> dict[str, Any]:
    mid = resolve_mode_id(mode_id)
    base = dict(MODE_META.get(mid) or {})
    base["mode_id"] = mid
    return base


def can_read_mode_data(reader_id: str, target_mode_id: str) -> bool:
    """Evrim tüm modları okur; diğerleri yalnızca kendi verisini."""
    reader = resolve_mode_id(reader_id)
    target = resolve_mode_id(target_mode_id)
    if reader == target:
        return True
    if reader == "evrim":
        return True
    return False


def is_paper_lab(mode_id: str) -> bool:
    return resolve_mode_id(mode_id) in PAPER_LAB_IDS


def enabled_mode_ids() -> tuple[str, ...]:
    """ELITE_ENABLED_MODES=berserk2 — yalnızca bu modlar paper/motor yükü alır."""
    raw = os.getenv("ELITE_ENABLED_MODES", "").strip()
    if not raw:
        return MODE_IDS
    out: list[str] = []
    seen: set[str] = set()
    for part in raw.replace(";", ",").split(","):
        mid = resolve_mode_id(part.strip())
        if mid in MODE_IDS and mid not in seen:
            seen.add(mid)
            out.append(mid)
    return tuple(out) if out else MODE_IDS


def berserk2_paper_only() -> bool:
    """BERSERK2 yalnız paper — canlı Binance emri gönderilmez."""
    return os.getenv("BERSERK2_PAPER_ONLY", "1").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def default_execution_mode_id() -> str:
    """Panel varsayılan motor — ELITE_DEFAULT_EXECUTION_MODE veya registry default."""
    raw = os.getenv("ELITE_DEFAULT_EXECUTION_MODE", "").strip()
    if raw:
        mid = resolve_mode_id(raw)
        if mid in MODE_IDS:
            return mid
    return DEFAULT_ACTIVE_FUTURES_MODE
