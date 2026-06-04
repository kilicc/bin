"""Evrim V2 — risk governor (DD, fee/gross, Sentinel, spread/slippage)."""
from __future__ import annotations

import time
from typing import Any

_sl_streak: dict[str, int] = {}
_sl_cooldown_until: dict[str, float] = {}

EXTREME_STOP_REASONS = frozenset({
    "api_latency",
    "daily_drawdown_halt",
    "sentinel_severe_risk_off",
    "spread_tp_veto",
    "slippage_tp_veto",
    "expected_net_negative",
    "symbol_sl_cooldown",
    "manual_stop",
    "binance_order_error",
})


def _f(profile: dict[str, Any], key: str, default: float) -> float:
    v = profile.get(key)
    return float(v) if v is not None else default


def is_extreme_stop(risk_result: dict[str, Any]) -> bool:
    reason = str(risk_result.get("risk_veto_reason") or "")
    return reason in EXTREME_STOP_REASONS and bool(risk_result.get("risk_veto"))


def record_sl(symbol: str, profile: dict[str, Any]) -> None:
    sym = str(symbol or "").upper()
    if not sym:
        return
    _sl_streak[sym] = _sl_streak.get(sym, 0) + 1
    if _sl_streak[sym] >= 3:
        cool_min = float(profile.get("market_cooldown_min") or 0.35)
        _sl_cooldown_until[sym] = time.time() + cool_min * 60.0 * 3


def record_win(symbol: str) -> None:
    sym = str(symbol or "").upper()
    if sym:
        _sl_streak[sym] = 0


def check_symbol_sl_cooldown(symbol: str) -> tuple[bool, float]:
    sym = str(symbol or "").upper()
    until = _sl_cooldown_until.get(sym)
    if not until:
        return True, 0.0
    now = time.time()
    if now >= until:
        _sl_cooldown_until.pop(sym, None)
        return True, 0.0
    return False, until - now


def assess_evrim_risk(
    signal: dict[str, Any],
    ctx: dict[str, Any],
    profile: dict[str, Any],
    meta: dict[str, Any],
    *,
    execution_path: str = "paper",
    recovery_score_boost: float = 0.0,
    in_recovery: bool = False,
) -> dict[str, Any]:
    reasons: list[str] = []
    stake_mult = 1.0
    veto = False
    veto_reason = ""

    daily_dd = float(ctx.get("daily_drawdown_pct") or meta.get("daily_drawdown_pct") or 0)
    fee_gross = float(ctx.get("fee_gross_ratio") or meta.get("fee_gross_ratio") or 0)
    expected = float(
        meta.get("expected_net_pnl_usd")
        or signal.get("expected_net_pnl")
        or hybrid_expected(signal)
        or 0
    )
    spread = float(ctx.get("spread_pct") or signal.get("spread_pct") or 0)
    slip = float(ctx.get("slippage_estimate") or signal.get("slippage_estimate") or 0)
    latency = float(ctx.get("api_latency_ms") or ctx.get("latency_ms") or 0)
    tp_pct = float(profile.get("tp_stake_pct") or 0.0042)
    order_error = bool(ctx.get("binance_order_error") or signal.get("binance_order_error"))

    half_dd = _f(profile, "evrim_v2_half_risk_drawdown_pct", 8)
    max_dd = _f(profile, "evrim_v2_max_daily_drawdown_pct", 12)
    fee_caution = _f(profile, "evrim_v2_fee_gross_caution", 0.45)
    fee_recovery = _f(profile, "evrim_v2_fee_gross_recovery", 0.75)
    spread_veto_frac = _f(profile, "evrim_v2_spread_tp_veto_frac", 0.65)
    slip_veto_frac = _f(profile, "evrim_v2_slippage_tp_veto_frac", 0.50)

    sentinel_mode = str(meta.get("sentinel_recommended_risk_mode") or "normal")
    sentinel_avoid = bool(meta.get("sentinel_risk_off"))
    sentinel_severe = (
        sentinel_avoid
        and sentinel_mode == "stop_new_entries"
    )

    risk_level = "normal"

    try:
        from elite_trader.evrim_learning_runtime import manual_stop_new_entries

        if manual_stop_new_entries(profile):
            veto = True
            veto_reason = "manual_stop"
            reasons.append("manual_stop")
            risk_level = "stop_new_entries"
    except Exception:
        pass

    if order_error:
        veto = True
        veto_reason = veto_reason or "binance_order_error"
        reasons.append("binance_order_error")
        risk_level = "stop_new_entries"

    if expected <= 0:
        veto = True
        veto_reason = veto_reason or "expected_net_negative"
        reasons.append("expected_net_negative")

    if spread > 0 and tp_pct > 0 and spread / tp_pct > spread_veto_frac:
        veto = True
        veto_reason = veto_reason or "spread_tp_veto"
        reasons.append("spread_tp_veto")

    if slip > 0 and tp_pct > 0 and slip / tp_pct > slip_veto_frac:
        veto = True
        veto_reason = veto_reason or "slippage_tp_veto"
        reasons.append("slippage_tp_veto")

    if latency >= 2500:
        veto = True
        veto_reason = veto_reason or "api_latency"
        reasons.append("api_latency")

    if sentinel_severe:
        veto = True
        veto_reason = veto_reason or "sentinel_severe_risk_off"
        reasons.append("sentinel_severe_risk_off")
        risk_level = "stop_new_entries"
    elif sentinel_avoid and sentinel_mode == "reduce_size":
        stake_mult *= 0.65
        risk_level = "reduce_size"
        reasons.append("sentinel_reduce_size")
    elif sentinel_mode == "paper_only":
        risk_level = "paper_only"
        reasons.append("sentinel_paper_only_recommendation")

    if daily_dd >= max_dd and execution_path == "live":
        veto = True
        veto_reason = veto_reason or "daily_drawdown_halt"
        reasons.append("daily_drawdown_halt")
        risk_level = "stop_new_entries"
    elif daily_dd >= half_dd:
        stake_mult *= 0.5
        if risk_level == "normal":
            risk_level = "cautious"
        reasons.append("daily_drawdown_half_risk")

    if fee_gross >= fee_recovery:
        stake_mult *= 0.5
        if risk_level in ("normal", "cautious", "reduce_size"):
            risk_level = "recovery"
        reasons.append("fee_gross_recovery")
    elif fee_gross >= fee_caution:
        stake_mult *= 0.75
        if risk_level == "normal":
            risk_level = "cautious"
        reasons.append("fee_gross_caution")

    if sentinel_mode == "reduce_size" and risk_level == "normal":
        stake_mult *= 0.65
        risk_level = "reduce_size"

    sym = str(signal.get("symbol") or "")
    ok_cd, cd_rem = check_symbol_sl_cooldown(sym)
    if not ok_cd:
        veto = True
        veto_reason = veto_reason or "symbol_sl_cooldown"
        reasons.append("symbol_sl_cooldown")

    final_score = float(meta.get("final_score") or 0)
    min_sc = _f(profile, "evrim_v2_min_final_score", 55)
    effective_min = min_sc + float(recovery_score_boost or 0)
    if final_score < effective_min:
        if in_recovery or recovery_score_boost > 0:
            reasons.append("final_score_below_recovery_bar")
        else:
            veto = True
            veto_reason = veto_reason or "final_score_low"
            reasons.append("final_score_low")

    try:
        from elite_trader.evrim_learning_runtime import (
            learning_blocks_trading,
            set_risk_mode_during_learning,
        )

        if learning_blocks_trading():
            veto = True
            veto_reason = veto_reason or "learning_blocks_trading"
        set_risk_mode_during_learning(risk_level)
    except Exception:
        pass

    return {
        "risk_level": risk_level,
        "risk_veto": veto,
        "risk_veto_reason": veto_reason,
        "risk_reasons": reasons,
        "risk_stake_mult": round(stake_mult, 4),
        "avoid_market_now": sentinel_severe or (daily_dd >= half_dd and fee_gross >= fee_caution),
        "recommended_risk_mode": risk_level if risk_level != "normal" else sentinel_mode,
        "symbol_sl_cooldown_remaining": round(cd_rem, 1) if not ok_cd else 0.0,
        "effective_min_final_score": round(effective_min, 2),
        "is_extreme_stop": is_extreme_stop({"risk_veto": veto, "risk_veto_reason": veto_reason}),
    }


def hybrid_expected(signal: dict[str, Any]) -> float:
    h = signal.get("evrim_hybrid") or {}
    return float(h.get("expected_net_pnl_usd") or 0)


def reset_governor_stats() -> None:
    _sl_streak.clear()
    _sl_cooldown_until.clear()
