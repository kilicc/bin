"""Evrim V2 — graduated recovery mode."""
from __future__ import annotations

import time
from typing import Any

_state: dict[str, Any] = {
    "active": False,
    "entered_at": 0.0,
    "positive_trades": 0,
    "reason": "",
}


def recovery_state() -> dict[str, Any]:
    return dict(_state)


def reset_recovery() -> None:
    _state.update(active=False, entered_at=0.0, positive_trades=0, reason="")


def maybe_enter_recovery(
    ctx: dict[str, Any],
    meta: dict[str, Any],
    profile: dict[str, Any],
) -> dict[str, Any]:
    fee_gross = float(ctx.get("fee_gross_ratio") or 0)
    fee_recovery = float(profile.get("evrim_v2_fee_gross_recovery") or 0.75)
    pf = float(ctx.get("profit_factor") or meta.get("profit_factor") or 1.0)
    sl_streak = int(ctx.get("consecutive_sl") or 0)
    sentinel_off = bool(meta.get("sentinel_risk_off"))
    paper_degraded = bool(ctx.get("paper_performance_degraded"))

    triggers: list[str] = []
    if sl_streak >= 3:
        triggers.append("sl_streak")
    if fee_gross >= fee_recovery:
        triggers.append("fee_gross")
    if pf < 0.85:
        triggers.append("low_pf")
    if sentinel_off:
        triggers.append("sentinel_risk_off")
    if paper_degraded:
        triggers.append("paper_degraded")

    if triggers and not _state["active"]:
        _state.update(active=True, entered_at=time.time(), positive_trades=0, reason=",".join(triggers))

    if not _state["active"]:
        return {"recovery_mode": False, "recovery_reason": ""}

    stake_mult = 0.5
    score_boost = 5.0
    spread_tighten = 0.85

    return {
        "recovery_mode": True,
        "recovery_reason": _state.get("reason") or "",
        "recovery_stake_mult": stake_mult,
        "recovery_score_boost": score_boost,
        "recovery_spread_mult": spread_tighten,
    }


def record_recovery_trade(pnl: float) -> None:
    if not _state["active"]:
        return
    if pnl > 0:
        _state["positive_trades"] = int(_state.get("positive_trades") or 0) + 1
    if int(_state.get("positive_trades") or 0) >= 5:
        reset_recovery()
    elif time.time() - float(_state.get("entered_at") or 0) > 1800:
        reset_recovery()
