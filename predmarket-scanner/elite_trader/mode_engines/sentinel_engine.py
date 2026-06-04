"""SENTINEL — kalite / trend / execution benchmark motoru."""
from __future__ import annotations

from typing import Any

from elite_trader.mode_engines.sentinel_scoring import (
    assess_sentinel_risk_off,
    calculate_execution_quality_score,
    calculate_sentinel_quality_score,
    evaluate_sentinel_spread,
    resolve_sentinel_dynamic_exit,
    resolve_sentinel_stake_mult,
)


def _profile(ctx: dict[str, Any]) -> dict[str, Any]:
    return dict(ctx.get("profile") or {})


def _trend_conflicts(side: str, ctx: dict[str, Any], profile: dict[str, Any]) -> bool:
    mode = str(profile.get("sentinel_trend_misalignment_mode") or "veto").lower()
    if mode != "veto":
        return False
    trend = str(ctx.get("trend_bias") or ctx.get("trend") or "").upper()
    if not trend or trend in ("NEUTRAL", "FLAT", "NONE"):
        return False
    return trend not in (side, side.lower(), "UP" if side == "LONG" else "DOWN")


def evaluate(signal: dict[str, Any], ctx: dict[str, Any]) -> tuple[bool, str]:
    profile = _profile(ctx)
    side = str(signal.get("type") or "LONG").upper()
    strength = str(signal.get("strength") or "Medium")
    regime = str(ctx.get("regime") or signal.get("market_regime") or "").lower()

    min_q = float(profile.get("sentinel_min_quality_score") or 62)
    exec_min = float(profile.get("sentinel_min_execution_score") or 62)
    allow_medium = bool(profile.get("sentinel_allow_medium_if_quality", True))
    news_mode = str(profile.get("sentinel_news_risk_mode") or "risk_off").lower()

    ch = float(signal.get("change") or 0)
    ctx = {
        **ctx,
        "change_pct": ch,
        "spread_pct": float(ctx.get("spread_pct") or signal.get("spread_pct") or 0.06),
    }

    quality = calculate_sentinel_quality_score(signal, ctx, profile)
    execution = calculate_execution_quality_score(signal, ctx, profile, quality)
    spread = evaluate_sentinel_spread(
        float(ctx["spread_pct"]),
        float(profile.get("min_stake_usd") or 180),
        profile,
    )
    risk = assess_sentinel_risk_off(signal, ctx, profile, quality, execution)

    q_score = float(quality["sentinel_quality_score"])
    exec_score = float(execution["sentinel_execution_quality_score"])

    spread_delta = int(spread.get("quality_score_delta") or 0)
    if spread_delta:
        q_score = round(min(100.0, max(0.0, q_score + spread_delta)), 2)
        quality["sentinel_quality_score"] = q_score
        if q_score >= 88:
            quality["sentinel_quality_tier"] = "premium"
            quality["sentinel_premium_signal"] = True
        elif q_score >= 75:
            quality["sentinel_quality_tier"] = "high_quality"
        elif q_score >= 62:
            quality["sentinel_quality_tier"] = "paper_candidate"
        elif q_score >= 55:
            quality["sentinel_quality_tier"] = "watch"
        else:
            quality["sentinel_quality_tier"] = "observation"

    stake_mult = resolve_sentinel_stake_mult(strength, quality, spread, profile)
    dyn_exit = resolve_sentinel_dynamic_exit(
        float(profile.get("min_stake_usd") or 180),
        q_score,
        profile,
    )

    meta: dict[str, Any] = {
        **quality,
        **execution,
        **spread,
        **risk,
        "quality_breakdown": quality.get("sentinel_quality_breakdown"),
        "premium_signal": quality.get("sentinel_premium_signal"),
        "sentinel_stake_mult": stake_mult,
        "sentinel_dynamic_exit": dyn_exit,
        "expected_net_pnl": quality.get("expected_net_pnl_usd"),
        "sentinel_regime": regime,
    }
    signal["sentinel_meta"] = meta
    signal["sentinel_quality_score"] = q_score
    signal["sentinel_execution_quality_score"] = exec_score
    signal["sentinel_safe_market_score"] = quality.get("sentinel_safe_market_score")
    signal["expected_net_pnl"] = quality.get("expected_net_pnl_usd")

    if news_mode == "risk_off" and (ctx.get("news_shock") or signal.get("news_shock")):
        _log_reject(signal, "sentinel_news_off", meta)
        return False, "sentinel_news_off"

    if risk.get("sentinel_risk_off") and risk.get("recommended_risk_mode") in (
        "stop_new_entries",
        "paper_only",
    ):
        _log_reject(signal, "risk_off", meta)
        return False, "risk_off"

    min_fs = float(profile.get("sentinel_min_formula_score_engine") or 0.58)
    fs = float(ctx.get("formula_score") or signal.get("formula_score") or 0)
    if fs > 0 and fs < min_fs:
        _log_reject(signal, "formula", meta)
        return False, "formula"

    if strength == "Weak" and profile.get("entry_block_weak", True):
        _log_reject(signal, "sentinel_weak_observation", meta)
        return False, "sentinel_weak_observation"

    if spread.get("spread_veto"):
        _log_reject(signal, "spread_risk", meta)
        return False, "spread_risk"

    if exec_score < exec_min:
        _log_reject(signal, "execution_quality_low", meta)
        return False, "execution_quality_low"

    if float(quality.get("expected_net_pnl_usd") or 0) < 0:
        _log_reject(signal, "expected_net_negative", meta)
        return False, "expected_net_negative"

    low_floor = max(40.0, min_q - 5.0)
    if q_score < low_floor:
        _log_reject(signal, "sentinel_low_quality", meta)
        return False, "sentinel_low_quality"

    if low_floor <= q_score < min_q:
        _log_reject(signal, "sentinel_watch", meta)
        return False, "sentinel_watch"

    if strength == "Medium" and not allow_medium:
        _log_reject(signal, "strength", meta)
        return False, "strength"

    if strength == "Medium" and q_score < min_q:
        _log_reject(signal, "sentinel_low_quality", meta)
        return False, "sentinel_low_quality"

    if q_score < min_q:
        _log_reject(signal, "sentinel_low_quality", meta)
        return False, "sentinel_low_quality"

    if "chop" in regime:
        chop_premium = float(profile.get("sentinel_chop_premium_min_score") or 85)
        if q_score < chop_premium:
            _log_reject(signal, "sentinel_chop_risk", meta)
            return False, "sentinel_chop_risk"
        meta["sentinel_chop_premium_only"] = True
        meta["sentinel_stake_mult"] = min(stake_mult, 0.45)

    if _trend_conflicts(side, ctx, profile):
        _log_reject(signal, "sentinel_trend_misalign", meta)
        return False, "sentinel_trend_misalign"

    try:
        from elite_trader.sentinel_benchmark import on_sentinel_decision

        on_sentinel_decision(signal, allowed=True, reason="sentinel_ok")
    except Exception:
        pass

    return True, ""


def _log_reject(signal: dict[str, Any], reason: str, meta: dict[str, Any]) -> None:
    try:
        from elite_trader.sentinel_benchmark import on_sentinel_decision

        on_sentinel_decision(signal, allowed=False, reason=reason, meta=meta)
    except Exception:
        pass
