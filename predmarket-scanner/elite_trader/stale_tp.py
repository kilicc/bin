"""Slot rotasyonu: TP'ye gitmeyen kârı al; zarardan kara dönünce de kapat."""
from __future__ import annotations

import os
from datetime import datetime, timezone


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, str(default)))
    except ValueError:
        return default


def _stale_mode() -> str:
    return os.getenv("ELITE_STALE_MODE", "flat_release").strip().lower()


def _enabled() -> bool:
    if os.getenv("ELITE_STALE_TP_FORCE", "0").strip().lower() in (
        "1",
        "true",
        "yes",
    ):
        return True
    if os.getenv("ELITE_STALE_TP_ENABLED", "0").strip().lower() not in (
        "1",
        "true",
        "yes",
    ):
        return False
    if _stale_mode() == "flat_release":
        return True
    port = (os.getenv("DASHBOARD_PORT") or "").strip()
    label = (os.getenv("SCENARIO_LABEL") or os.getenv("PROFILE_NAME") or "").strip()
    db = (os.getenv("PAPER_DB_PATH") or "").lower()
    return (
        port in ("8200", "8300")
        or label in ("elite_apex_2x_24h", "elite_apex_2x_paper_compound")
        or "apex_2x" in db
    )


def min_age_seconds() -> float:
    try:
        return float(os.getenv("ELITE_STALE_TP_MIN_AGE_MIN", "2")) * 60.0
    except ValueError:
        return 120.0


def position_age_seconds(opened_at: str | None) -> float:
    if not opened_at:
        return 0.0
    try:
        opened = datetime.fromisoformat(str(opened_at).replace("Z", "+00:00"))
        if opened.tzinfo is None:
            opened = opened.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - opened).total_seconds()
    except Exception:
        return 0.0


def _below_tp(unrealized_usd: float, tp_target_usd: float) -> bool:
    if tp_target_usd <= 0:
        return False
    return unrealized_usd < tp_target_usd * 0.995


def _min_take_profit_usd(stake_usd: float) -> float:
    """Kâr sayılması — komisyon sonrası net kâr için taban (STALE zararda kapanmasın)."""
    from elite_trader.symbol_quality import round_trip_fee_usd

    floor = _env_float("ELITE_STALE_MIN_UNREAL_USD", 0.30)
    if stake_usd > 0:
        pct = stake_usd * _env_float("ELITE_STALE_MIN_UNREAL_PCT", 0.0015)
        floor = max(floor, pct)
        fee_floor = round_trip_fee_usd(stake_usd, 3) * _env_float(
            "ELITE_STALE_FEE_COVER_MULT", 1.15
        )
        floor = max(floor, fee_floor)
    return floor


def _loss_seen_threshold_usd(stake_usd: float) -> float:
    """Bu kadar zarar gördüyse 'zararda idi' sayılır (recovery için)."""
    usd = _env_float("ELITE_STALE_LOSS_SEEN_USD", 0.60)
    if stake_usd > 0:
        usd = max(usd, stake_usd * _env_float("ELITE_STALE_LOSS_SEEN_PCT", 0.002))
    return -abs(usd)


def _keep_waiting_for_tp(unrealized_usd: float, tp_target_usd: float) -> bool:
    keep_frac = _env_float("ELITE_STALE_KEEP_IF_TP_PROGRESS", 0.55)
    return keep_frac > 0 and unrealized_usd >= tp_target_usd * keep_frac


def position_release_reason(
    *,
    opened_at: str | None,
    unrealized_usd: float,
    tp_target_usd: float,
    stake_usd: float = 0.0,
    min_unreal_seen: float = 0.0,
) -> str:
    """
    Kapanış nedeni veya ''.
    STALE-RELEASE: 2dk+ TP yok, kârdasın → kârı al
    STALE-RECOVER: zararda iken kara döndü, TP yok → kârı al
    """
    if not _enabled() or _stale_mode() != "flat_release":
        return _legacy_release_reason(
            opened_at=opened_at,
            unrealized_usd=unrealized_usd,
            tp_target_usd=tp_target_usd,
            stake_usd=stake_usd,
        )
    if not _below_tp(unrealized_usd, tp_target_usd):
        return ""
    min_tp = _min_take_profit_usd(stake_usd)
    if unrealized_usd < min_tp:
        return ""
    if _keep_waiting_for_tp(unrealized_usd, tp_target_usd):
        return ""

    age = position_age_seconds(opened_at)
    loss_thr = _loss_seen_threshold_usd(stake_usd)
    recover_min_age = _env_float("ELITE_STALE_RECOVER_MIN_AGE_SEC", 30)

    if (
        min_unreal_seen <= loss_thr
        and unrealized_usd >= min_tp
        and age >= recover_min_age
    ):
        return "STALE-RECOVER"

    if age >= min_age_seconds():
        return "STALE-RELEASE"

    return ""


def _legacy_release_reason(
    *,
    opened_at: str | None,
    unrealized_usd: float,
    tp_target_usd: float,
    stake_usd: float,
) -> str:
    if not _enabled():
        return ""
    if unrealized_usd < 0 or tp_target_usd <= 0 or unrealized_usd >= tp_target_usd:
        return ""
    if stake_usd > 0:
        band = stake_usd * _env_float("ELITE_STALE_BREAKEVEN_PCT", 0.006)
        if unrealized_usd > band:
            return ""
    min_prog = _env_float("ELITE_STALE_MIN_TP_PROGRESS", 0.40)
    if unrealized_usd > 0 and unrealized_usd >= tp_target_usd * min_prog:
        return ""
    if position_age_seconds(opened_at) >= min_age_seconds():
        return "STALE-TP"
    return ""


def should_close_stale(
    *,
    opened_at: str | None,
    unrealized_usd: float,
    tp_target_usd: float,
    stake_usd: float = 0.0,
    min_unreal_seen: float = 0.0,
) -> bool:
    return bool(
        position_release_reason(
            opened_at=opened_at,
            unrealized_usd=unrealized_usd,
            tp_target_usd=tp_target_usd,
            stake_usd=stake_usd,
            min_unreal_seen=min_unreal_seen,
        )
    )


def exit_reason_blocks_reopen(exit_reason: str | None) -> bool:
    """STALE kapanışları — aynı sembolde hızlı yeniden giriş (cooldown env ile)."""
    ex = (exit_reason or "").upper()
    return ex not in (
        "STALE-TP",
        "STALE-RELEASE",
        "STALE-RECOVER",
        "TP-STALE",
        "STALE",
    )
