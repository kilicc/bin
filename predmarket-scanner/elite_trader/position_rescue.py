"""Hızlı TP (TP-TIMER) + 10dk / -$2 kurtarma (hedge veya reverse)."""
from __future__ import annotations

import os
import time
from typing import Any

__all__ = (
    "fast_tp_max_hold_sec",
    "has_rescue_for",
    "is_rescue_position",
    "needs_rescue",
    "opposite_side",
    "pick_rescue_action",
    "rescue_enabled",
    "rescue_loss_usd",
    "rescue_max_extra",
    "rescue_max_open_cap",
    "rescue_min_age_sec",
    "rescue_stake_frac",
    "tp_timer_enabled",
    "tp_timer_exit_reason",
)


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, str(default)))
    except ValueError:
        return default


def _env_bool(key: str, default: bool = False) -> bool:
    v = os.getenv(key, "1" if default else "0").strip().lower()
    return v in ("1", "true", "yes")


def tp_timer_enabled() -> bool:
    return _env_bool("ELITE_TP_TIMER_ENABLED", True)


def rescue_enabled() -> bool:
    return _env_bool("ELITE_RESCUE_ENABLED", True)


def fast_tp_max_hold_sec() -> float:
    return max(60.0, _env_float("ELITE_FAST_TP_MAX_HOLD_MIN", 8.0) * 60.0)


def rescue_min_age_sec() -> float:
    return max(60.0, _env_float("ELITE_RESCUE_MIN_AGE_MIN", 10.0) * 60.0)


def rescue_loss_usd() -> float:
    return max(0.5, _env_float("ELITE_RESCUE_LOSS_USD", 2.0))


def rescue_max_extra() -> int:
    return max(0, int(_env_float("ELITE_RESCUE_MAX_EXTRA", 3)))


def rescue_stake_frac() -> float:
    return min(1.0, max(0.15, _env_float("ELITE_HEDGE_STAKE_FRAC", 0.38)))


def rescue_mode() -> str:
    return os.getenv("ELITE_RESCUE_MODE", "auto").strip().lower()


def rescue_max_open_cap(base_cap: int) -> int:
    if not rescue_enabled():
        return base_cap
    return base_cap + rescue_max_extra()


def is_rescue_position(pos: dict[str, Any] | None) -> bool:
    if not pos:
        return False
    if pos.get("rescue_leg"):
        return True
    src = str(pos.get("signal_source") or "")
    return src.startswith("Rescue")


def opposite_side(side: str) -> str:
    return "SHORT" if str(side or "LONG").upper() == "LONG" else "LONG"


def _position_age_sec(pos: dict[str, Any]) -> float:
    from elite_trader.panel_strategy import position_age_seconds

    return position_age_seconds(pos)


def tp_timer_exit_reason(
    pos: dict[str, Any],
    *,
    mode_id: str | None = None,
    client: Any | None = None,
) -> str | None:
    """Max hold dolunca yalnızca book fill net > min ($0.40) doğrulanırsa TP-TIMER."""
    if not tp_timer_enabled() or not pos:
        return None
    age = _position_age_sec(pos)
    if age < fast_tp_max_hold_sec():
        return None
    unreal = float(pos.get("unrealized_pnl") or 0)
    if age >= rescue_min_age_sec() and unreal <= -rescue_loss_usd():
        return None
    if not pos.get("on_exchange") or client is None or getattr(client, "paper", True):
        return None
    try:
        from elite_trader.exchange_fill_truth import fill_net_close_ready

        ok, _final, _floor, _est = fill_net_close_ready(
            pos, client=client, mode_id=mode_id
        )
        if ok:
            return "TP-TIMER"
    except Exception:
        pass
    return None


def needs_rescue(pos: dict[str, Any]) -> bool:
    if not rescue_enabled() or not pos or is_rescue_position(pos):
        return False
    if pos.get("rescue_pending"):
        return False
    age = _position_age_sec(pos)
    if age < rescue_min_age_sec():
        return False
    unreal = float(pos.get("unrealized_pnl") or 0)
    return unreal <= -rescue_loss_usd()


def has_rescue_for(pos: dict[str, Any], all_positions: list[dict[str, Any]]) -> bool:
    pid = pos.get("id")
    sym = str(pos.get("symbol") or "")
    for p in all_positions:
        if p.get("rescue_of_id") == pid:
            return True
        if (
            str(p.get("symbol") or "") == sym
            and is_rescue_position(p)
            and p.get("rescue_of_id") == pid
        ):
            return True
    return False


def pick_rescue_action(
    pos: dict[str, Any],
    all_positions: list[dict[str, Any]],
) -> str | None:
    if not needs_rescue(pos) or has_rescue_for(pos, all_positions):
        return None
    mode = rescue_mode()
    if mode == "hedge":
        return "hedge"
    if mode in ("reverse", "flip"):
        return "reverse"
    hedge_age = _env_float("ELITE_RESCUE_REVERSE_AFTER_MIN", 15.0) * 60.0
    age = _position_age_sec(pos)
    if age >= hedge_age:
        return "reverse"
    return "hedge"


def rescue_cooldown_ok(pos: dict[str, Any], *, cooldown_sec: float = 90.0) -> bool:
    last = float(pos.get("rescue_last_attempt_ts") or 0)
    return (time.time() - last) >= cooldown_sec


def mark_rescue_attempt(pos: dict[str, Any]) -> None:
    pos["rescue_last_attempt_ts"] = time.time()
    pos["rescue_pending"] = True
