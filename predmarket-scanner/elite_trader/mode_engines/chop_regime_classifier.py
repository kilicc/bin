"""Chop V2 — regime classifier (chop_score 0-100)."""
from __future__ import annotations

from typing import Any


def _f(profile: dict[str, Any], key: str, default: float) -> float:
    v = profile.get(key)
    return float(v) if v is not None else default


def classify_chop_regime(
    signal: dict[str, Any],
    ctx: dict[str, Any],
    profile: dict[str, Any],
) -> dict[str, Any]:
    adx = float(ctx.get("adx") or signal.get("adx") or 25)
    atr = float(ctx.get("atr_pct") or signal.get("atr_pct") or 0)
    ch = abs(float(signal.get("change") or 0))
    vr = float(ctx.get("vol_ratio") or signal.get("vol_ratio") or 1.0)
    wick = float(signal.get("wick_ratio") or ctx.get("wick_ratio") or 0)
    body = float(ctx.get("candle_body_ratio") or signal.get("candle_body_ratio") or 0.5)
    range_w = float(ctx.get("range_width_pct") or signal.get("range_width_pct") or 0)
    near_vwap = bool(ctx.get("near_vwap") if ctx.get("near_vwap") is not None else signal.get("near_vwap", True))
    ema_tangled = bool(ctx.get("ema_tangled") or signal.get("ema_tangled"))
    failed_br = bool(ctx.get("failed_breakout") or signal.get("failed_breakout"))
    mean_revert = bool(ctx.get("mean_revert_bias") or signal.get("mean_revert_bias"))

    reasons: list[str] = []
    score = 0.0

    if adx < 22:
        score += 18
        reasons.append("low_adx")
    elif adx < 28:
        score += 10
        reasons.append("moderate_adx")

    if ema_tangled or adx < 25:
        score += 12
        reasons.append("ema_tangled")

    if near_vwap:
        score += 10
        reasons.append("vwap_centered")

    if 0.08 <= atr <= 0.35:
        score += 8
        reasons.append("atr_range_ok")
    elif atr < 0.08:
        score += 5
        reasons.append("low_atr")

    if range_w >= 0.12:
        score += 12
        reasons.append("range_defined")
    elif range_w >= 0.06:
        score += 6
        reasons.append("range_moderate")

    if failed_br:
        score += 8
        reasons.append("failed_breakouts")

    if body < 0.35:
        score += 6
        reasons.append("small_body")
    if wick > 0.45:
        score += 6
        reasons.append("frequent_wicks")

    if mean_revert:
        score += 8
        reasons.append("mean_revert_bias")

    if ch < 0.25 and vr < 1.35:
        score += 6
        reasons.append("no_trend_burst")

    score = min(100.0, score)

    obs_min = _f(profile, "chop_observation_min", 45)
    trade_min = _f(profile, "chop_min_score_trade", 65)
    strong_min = _f(profile, "chop_strong_score", 80)

    if score < obs_min:
        tier = "trend_possible"
    elif score < trade_min:
        tier = "observation"
    elif score < strong_min:
        tier = "normal_chop"
    else:
        tier = "strong_mean_reversion"

    range_quality = min(100.0, range_w * 200.0 + (12 if range_w >= 0.12 else 0))
    mr_prob = min(100.0, score * 0.65 + range_quality * 0.35)

    return {
        "chop_score": round(score, 2),
        "chop_tier": tier,
        "chop_reason": reasons,
        "range_quality": round(range_quality, 2),
        "mean_reversion_probability": round(mr_prob, 2),
    }
