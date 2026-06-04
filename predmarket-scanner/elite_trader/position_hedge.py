"""Canlı hedge — ana pozisyon açık kalır; ters bacak ayrı TP ile kapanır (reverse yok)."""
from __future__ import annotations

import os
import time
from typing import Any

__all__ = (
    "has_hedge_for",
    "hedge_cooldown_ok",
    "hedge_exchange_supported",
    "hedge_live_enabled",
    "hedge_max_extra",
    "hedge_max_open_cap",
    "hedge_stake_frac",
    "is_hedge_leg",
    "mark_hedge_attempt",
    "needs_live_hedge",
    "opposite_side",
)


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, str(default)))
    except ValueError:
        return default


def _env_bool(key: str, default: bool = False) -> bool:
    v = os.getenv(key, "1" if default else "0").strip().lower()
    return v in ("1", "true", "yes")


def hedge_live_enabled() -> bool:
    return _env_bool("ELITE_HEDGE_LIVE_ENABLED", True)


def hedge_exchange_supported(*, client: Any | None = None) -> bool:
    """
    Binance one-way (positionSide=BOTH): ters emir ana pozisyonu netler/kapatır.
    Ayrı hedge bacak yalnızca dual-side (hedge mode) hesapta mümkün — şu an kapalı.
    """
    if not hedge_live_enabled():
        return False
    if _env_bool("ELITE_HEDGE_REQUIRE_DUAL_SIDE", True):
        return False
    if client is not None and getattr(client, "paper", True):
        return False
    return True


def hedge_proactive_enabled() -> bool:
    return _env_bool("ELITE_HEDGE_PROACTIVE", True)


def hedge_stake_frac() -> float:
    return min(1.0, max(0.15, _env_float("ELITE_HEDGE_STAKE_FRAC", 0.38)))


def hedge_max_extra() -> int:
    return max(0, int(_env_float("ELITE_HEDGE_MAX_EXTRA", 3)))


def hedge_max_open_cap(base_cap: int) -> int:
    if not hedge_live_enabled():
        return base_cap
    return base_cap + hedge_max_extra()


def hedge_loss_usd() -> float:
    return max(0.5, _env_float("ELITE_HEDGE_LOSS_USD", 2.0))


def hedge_min_age_sec() -> float:
    return max(60.0, _env_float("ELITE_HEDGE_MIN_AGE_MIN", 10.0) * 60.0)


def hedge_proactive_pct() -> float:
    return max(0.001, _env_float("ELITE_HEDGE_PROACTIVE_PCT", 0.005))


def is_hedge_leg(pos: dict[str, Any] | None) -> bool:
    if not pos:
        return False
    if pos.get("hedge_leg"):
        return True
    return str(pos.get("signal_source") or "").startswith("Hedge")


def opposite_side(side: str) -> str:
    return "SHORT" if str(side or "LONG").upper() == "LONG" else "LONG"


def _position_age_sec(pos: dict[str, Any]) -> float:
    from elite_trader.panel_strategy import position_age_seconds

    return position_age_seconds(pos)


def has_hedge_for(pos: dict[str, Any], all_positions: list[dict[str, Any]]) -> bool:
    pid = pos.get("id")
    sym = str(pos.get("symbol") or "")
    for p in all_positions:
        if p.get("hedge_of_id") == pid and is_hedge_leg(p):
            return True
        if (
            str(p.get("symbol") or "") == sym
            and is_hedge_leg(p)
            and p.get("hedge_of_id") == pid
        ):
            return True
    return False


def needs_live_hedge(pos: dict[str, Any]) -> bool:
    """Ana pozisyon için ters hedge açılmalı mı? (kapatma yok)."""
    if not hedge_live_enabled() or not pos:
        return False
    if is_hedge_leg(pos) or pos.get("rescue_leg"):
        return False
    if pos.get("hedge_pending"):
        return False
    if not pos.get("on_exchange"):
        return False

    stake = max(float(pos.get("stake_usd") or 1), 1.0)
    unreal = float(pos.get("unrealized_pnl") or 0)
    age = _position_age_sec(pos)

    if hedge_proactive_enabled() and unreal <= -(stake * hedge_proactive_pct()):
        return True

    if age >= hedge_min_age_sec() and unreal <= -hedge_loss_usd():
        return True

    return False


def hedge_cooldown_ok(pos: dict[str, Any], *, cooldown_sec: float = 90.0) -> bool:
    last = float(pos.get("hedge_last_attempt_ts") or 0)
    return (time.time() - last) >= cooldown_sec


def mark_hedge_attempt(pos: dict[str, Any]) -> None:
    pos["hedge_last_attempt_ts"] = time.time()
    pos["hedge_pending"] = True
