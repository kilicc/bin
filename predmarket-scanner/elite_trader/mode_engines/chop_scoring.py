"""Chop V2 — scoring, trend guard, spread/fee, range TP/SL."""
from __future__ import annotations

from typing import Any

from elite_trader.mode_engines.chop_failed_breakout import detect_failed_breakout_reversal
from elite_trader.mode_engines.chop_mean_reversion_engine import calculate_mean_reversion_score
from elite_trader.mode_engines.chop_regime_classifier import classify_chop_regime

STRENGTH_STAKE_MULT = {"Weak": 0.50, "Medium": 0.85, "Strong": 1.0}


def _f(profile: dict[str, Any], key: str, default: float) -> float:
    v = profile.get(key)
    return float(v) if v is not None else default


def spread_assessment(spread_pct: float, profile: dict[str, Any]) -> dict[str, Any]:
    sp = max(0.0, float(spread_pct))
    max_sp = _f(profile, "chop_max_spread_pct", 0.12)
    soft = _f(profile, "chop_spread_soft_start", 0.05)
    limit_start = _f(profile, "chop_spread_limit_start", 0.09)
    out: dict[str, Any] = {
        "spread_pct": sp,
        "spread_risk_level": "normal",
        "stake_mult": 1.0,
        "veto": False,
        "limit_order_only": False,
        "spread_penalty_applied": False,
    }
    if sp <= soft:
        return out
    if sp <= limit_start:
        out["spread_risk_level"] = "elevated"
        out["stake_mult"] = 0.65
        out["spread_penalty_applied"] = True
        return out
    if sp <= max_sp:
        out["spread_risk_level"] = "high"
        out["stake_mult"] = 0.45
        out["limit_order_only"] = True
        out["spread_penalty_applied"] = True
        return out
    out["spread_risk_level"] = "extreme"
    out["veto"] = True
    return out


def evaluate_trend_guard(
    signal: dict[str, Any],
    ctx: dict[str, Any],
    profile: dict[str, Any],
) -> dict[str, Any]:
    adx = float(ctx.get("adx") or signal.get("adx") or 25)
    adx_rising = bool(ctx.get("adx_rising") or signal.get("adx_rising"))
    atr_exp = bool(ctx.get("atr_expansion") or signal.get("atr_expansion"))
    vol_br = bool(ctx.get("volume_breakout") or signal.get("volume_breakout"))
    retest_ok = bool(ctx.get("range_retest_success") or signal.get("range_retest_success"))
    vwap_drift = bool(ctx.get("vwap_drift") or signal.get("vwap_drift"))
    ema_aligned = bool(ctx.get("ema_strong_aligned") or signal.get("ema_strong_aligned"))
    ch = abs(float(signal.get("change") or 0))
    hunter_br = float(
        ctx.get("hunter_breakout_score")
        or signal.get("hunter_breakout_score")
        or signal.get("breakout_score")
        or 0
    )
    hunter_veto = _f(profile, "chop_hunter_breakout_veto", 70)

    reasons: list[str] = []
    active = False
    if ema_aligned:
        active = True
        reasons.append("ema_aligned")
    if adx >= 28 and adx_rising:
        active = True
        reasons.append("adx_rising")
    if atr_exp:
        active = True
        reasons.append("atr_expansion")
    if vol_br:
        active = True
        reasons.append("volume_breakout")
    if retest_ok:
        active = True
        reasons.append("range_retest_success")
    if vwap_drift:
        active = True
        reasons.append("vwap_drift")
    if hunter_br >= hunter_veto:
        active = True
        reasons.append("hunter_breakout_high")
    if "trend" in str(ctx.get("regime") or signal.get("market_regime") or "").lower() and adx > 30 and ch > 0.35:
        active = True
        reasons.append("trend_regime")

    return {
        "trend_guard_active": active,
        "trend_guard_reason": reasons,
        "chop_trade_blocked": active,
        "chop_not_safe": active,
    }


def estimate_round_trip_cost_usd(stake_usd: float, spread_pct: float) -> float:
    from elite_trader.fee_economics import round_trip_fee_usd

    stake = max(float(stake_usd), 1.0)
    fee = round_trip_fee_usd(stake, 2, fee_mult=1.0)
    slip = stake * max(0.0, spread_pct) * 0.35
    return fee + slip


def resolve_range_tp_sl(
    profile: dict[str, Any],
    *,
    spread_pct: float,
    range_width_pct: float,
    chop_score: float,
    recovery_mode: bool = False,
) -> dict[str, float]:
    tp = _f(profile, "tp_stake_pct", 0.0028)
    sl = _f(profile, "sl_stake_pct", 0.0018)
    trig = _f(profile, "tp_trigger_frac", 0.99)
    if recovery_mode:
        tp *= 1.15
    if spread_pct > 0.05:
        sl = max(sl, spread_pct * 0.35)
    if chop_score >= 80:
        tp = min(0.0045, tp * 1.12)
    if range_width_pct > 0 and range_width_pct < 0.08:
        tp *= 0.85
    return {
        "tp_stake_pct": round(tp, 5),
        "sl_stake_pct": round(sl, 5),
        "tp_trigger_frac": trig,
        "partial_tp_frac": 0.50,
        "trailing_to_vwap": True,
    }


def evaluate_chop_entry(
    signal: dict[str, Any],
    ctx: dict[str, Any],
    profile: dict[str, Any],
    *,
    edge: float,
    formula: float,
) -> tuple[bool, str, dict[str, Any]]:
    meta: dict[str, Any] = {
        "strength_stake_mult": STRENGTH_STAKE_MULT.get(
            str(signal.get("strength") or "Medium"), 0.85
        ),
        "combined_stake_mult": STRENGTH_STAKE_MULT.get(
            str(signal.get("strength") or "Medium"), 0.85
        ),
        "spread_stake_mult": 1.0,
        "spread_risk_level": "normal",
    }

    trend = evaluate_trend_guard(signal, ctx, profile)
    meta.update(trend)
    if trend["trend_guard_active"]:
        try:
            from elite_trader.chop_cooldown import record_trend_guard_block

            record_trend_guard_block()
        except Exception:
            pass
        return False, "chop_trend_guard", meta

    chop = classify_chop_regime(signal, ctx, profile)
    meta.update(chop)
    chop_score = float(chop["chop_score"])
    obs_min = _f(profile, "chop_observation_min", 45)
    trade_min = _f(profile, "chop_min_score_trade", 65)

    if chop_score < obs_min:
        return False, "chop_score_low", meta
    if chop_score < trade_min:
        meta["chop_observation"] = True
        return False, "chop_observation", meta

    spread = float(ctx.get("spread_pct") or signal.get("spread_pct") or 0)
    sp_info = spread_assessment(spread, profile)
    meta["spread_pct"] = spread
    meta["spread_risk_level"] = sp_info["spread_risk_level"]
    meta["spread_stake_mult"] = sp_info["stake_mult"]
    meta["limit_order_only"] = sp_info.get("limit_order_only", False)
    if sp_info.get("veto"):
        return False, "chop_spread_veto", meta

    range_w = float(ctx.get("range_width_pct") or signal.get("range_width_pct") or 0)
    meta["range_width_pct"] = range_w
    stake_base = float(profile.get("min_stake_usd") or 120)
    cost = estimate_round_trip_cost_usd(stake_base, spread)
    meta["round_trip_cost_usd"] = round(cost, 4)

    min_range_mult = _f(profile, "chop_min_range_width_mult", 3.0)
    min_cost_pct = cost / max(stake_base, 1.0)
    if range_w > 0 and range_w < min_cost_pct * min_range_mult:
        meta["range_too_narrow"] = True
        try:
            from elite_trader.chop_cooldown import record_range_narrow_reject

            record_range_narrow_reject()
        except Exception:
            pass
        return False, "chop_range_too_narrow", meta
    if range_w > 0 and range_w < 0.04:
        meta["range_too_narrow"] = True
        try:
            from elite_trader.chop_cooldown import record_range_narrow_reject

            record_range_narrow_reject()
        except Exception:
            pass
        return False, "chop_range_too_narrow", meta

    tp_base = _f(profile, "tp_stake_pct", 0.0028) * _f(profile, "tp_trigger_frac", 0.99)
    if tp_base > 0 and spread / tp_base > 0.40:
        return False, "chop_spread_veto", meta

    failed = detect_failed_breakout_reversal(signal, ctx, profile)
    meta.update(failed)
    if failed.get("reversal_blocked"):
        return False, failed.get("reversal_block_reason") or "chop_reversal_blocked", meta

    mr = calculate_mean_reversion_score(signal, ctx, profile)
    meta.update(mr)

    reversal_ok = bool(failed.get("failed_breakout_detected"))
    mr_ok = bool(mr.get("mean_reversion_candidate"))
    if not reversal_ok and not mr_ok:
        return False, "chop_no_mean_reversion", meta

    expected_move_pct = range_w if range_w > 0 else abs(float(signal.get("change") or 0))
    min_move_mult = _f(profile, "chop_min_expected_move_mult", 1.4)
    meta["expected_move_pct"] = round(expected_move_pct, 4)
    if expected_move_pct < min_cost_pct * min_move_mult:
        return False, "chop_expected_move_low", meta

    recovery_mode = False
    fee_gross = float(ctx.get("fee_gross_ratio") or signal.get("fee_gross_ratio") or 0)
    meta["fee_gross_ratio_session"] = fee_gross
    if fee_gross >= 0.70:
        recovery_mode = True
        meta["chop_recovery_mode"] = True
    elif fee_gross >= 0.50:
        meta["chop_fee_pressure"] = True

    dyn = resolve_range_tp_sl(
        profile,
        spread_pct=spread,
        range_width_pct=range_w,
        chop_score=chop_score,
        recovery_mode=recovery_mode,
    )
    meta["dynamic_exit"] = dyn

    stake_mult = float(meta["strength_stake_mult"]) * float(sp_info["stake_mult"])
    stake_mult *= float(profile.get("entry_stake_mult") or 0.85)
    if recovery_mode:
        stake_mult *= 0.65
    meta["combined_stake_mult"] = round(stake_mult, 4)

    tp_usd = stake_base * stake_mult * dyn["tp_stake_pct"] * dyn["tp_trigger_frac"]
    expected_net = tp_usd - cost
    meta["expected_net_pnl_usd"] = round(expected_net, 4)
    signal["expected_net_pnl"] = meta["expected_net_pnl_usd"]
    if expected_net <= 0:
        return False, "chop_expected_net_negative", meta

    ch = abs(float(signal.get("change") or 0))
    if ch < 0.06 and not reversal_ok:
        return False, "chop_min_revert", meta

    signal["chop_meta"] = meta
    signal["spread_risk_level"] = meta["spread_risk_level"]
    return True, "", meta
