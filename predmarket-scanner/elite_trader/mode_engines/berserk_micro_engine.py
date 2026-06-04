"""Berserk V2 — micro momentum signal score (0-100)."""
from __future__ import annotations

from typing import Any

LEARNING_TAGS = {
    "Weak": "weak_micro_test",
    "Medium": "medium_micro_trade",
    "Strong": "strong_micro_momentum",
}


def _side(signal: dict[str, Any]) -> str:
    return str(signal.get("type") or signal.get("side") or "LONG").upper()


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _aligned(delta: float, side: str) -> bool:
    if abs(delta) < 1e-9:
        return False
    return (delta > 0) == (side == "LONG")


def _price_acceleration(signal: dict[str, Any], ctx: dict[str, Any]) -> float:
    ch = abs(float(signal.get("change") or ctx.get("change_pct") or 0))
    accel = float(ctx.get("micro_accel") or ctx.get("price_accel") or 0)
    if accel == 0:
        accel = ch * 0.55
    burst = float(ctx.get("micro_breakout") or 0)
    body = float(ctx.get("candle_body_accel") or 0)
    raw = ch * 6.0 + accel * 35.0 + burst * 8.0 + body * 5.0
    return _clamp(raw, 0.0, 25.0)


def _volume_burst(ctx: dict[str, Any], signal: dict[str, Any]) -> float:
    vr = float(ctx.get("vol_ratio") or signal.get("vol_ratio") or 1.0)
    vp = float(ctx.get("volume_pressure") or signal.get("volume_pressure") or 0)
    if vp == 0 and vr > 1:
        vp = vr - 1.0
    if vr >= 1.8:
        return 20.0
    if vr >= 1.4:
        return 14.0 + min(6.0, vp * 10)
    if vr >= 1.1:
        return 8.0 + min(6.0, vp * 8)
    return _clamp(vp * 12.0, 0.0, 8.0)


def _orderbook_pressure(ctx: dict[str, Any], signal: dict[str, Any], side: str) -> float:
    ob = float(ctx.get("orderbook_pressure") or signal.get("orderbook_pressure") or 0)
    flow = float(ctx.get("flow_bias") or signal.get("pool_flow_bias") or 0)
    imb = float(ctx.get("bid_ask_imbalance") or signal.get("bid_ask_imbalance") or 0)
    score = 6.0
    if _aligned(ob, side):
        score += min(8.0, abs(ob) * 12)
    if _aligned(flow, side):
        score += min(6.0, abs(flow) * 10)
    if _aligned(imb, side):
        score += min(6.0, abs(imb) * 8)
    return _clamp(score, 0.0, 20.0)


def _spread_quality(spread_pct: float) -> float:
    sp = max(0.0, float(spread_pct))
    if sp <= 0.04:
        return 15.0
    if sp <= 0.06:
        return 12.0
    if sp <= 0.08:
        return 8.0
    if sp <= 0.10:
        return 4.0
    return 1.0


def _micro_trend(ctx: dict[str, Any], signal: dict[str, Any], side: str) -> float:
    ema9 = float(ctx.get("ema9") or ctx.get("ema_9") or 0)
    ema21 = float(ctx.get("ema21") or ctx.get("ema_21") or 0)
    tb = str(ctx.get("trend_bias") or signal.get("trend_bias") or "").upper()
    above_vwap = ctx.get("above_vwap")
    score = 3.0
    if ema9 > 0 and ema21 > 0:
        if side == "LONG" and ema9 > ema21:
            score += 4.0
        elif side == "SHORT" and ema9 < ema21:
            score += 4.0
    if side == "LONG" and tb in ("LONG", "UP", "BULL"):
        score += 2.0
    elif side == "SHORT" and tb in ("SHORT", "DOWN", "BEAR"):
        score += 2.0
    if above_vwap is True and side == "LONG":
        score += 1.0
    elif above_vwap is False and side == "SHORT":
        score += 1.0
    return _clamp(score, 0.0, 10.0)


def _execution_speed(ctx: dict[str, Any]) -> float:
    lat = float(ctx.get("api_latency_ms") or ctx.get("latency_ms") or 200)
    tick_age = float(ctx.get("tick_age_ms") or 0)
    if lat <= 400 and tick_age <= 500:
        return 10.0
    if lat <= 800:
        return 7.0
    if lat <= 1500:
        return 4.0
    return 1.0


def calculate_micro_score(
    signal: dict[str, Any],
    ctx: dict[str, Any],
    profile: dict[str, Any],
) -> dict[str, Any]:
    side = _side(signal)
    spread_pct = float(ctx.get("spread_pct") or signal.get("spread_pct") or 0.06)
    breakdown = {
        "price_acceleration": round(_price_acceleration(signal, ctx), 2),
        "volume_burst": round(_volume_burst(ctx, signal), 2),
        "orderbook_pressure": round(_orderbook_pressure(ctx, signal, side), 2),
        "spread_quality": round(_spread_quality(spread_pct), 2),
        "micro_trend": round(_micro_trend(ctx, signal, side), 2),
        "execution_speed": round(_execution_speed(ctx), 2),
    }
    total = round(sum(breakdown.values()), 2)

    min_sc = float(profile.get("berserk_min_score") or 45)
    norm_sc = float(profile.get("berserk_normal_score") or 60)
    agg_sc = float(profile.get("berserk_aggressive_score") or 75)

    tier = "block"
    tier_stake_mult = 0.0
    if total < min_sc:
        tier = "block"
    elif total < norm_sc:
        tier = "paper_trial"
        tier_stake_mult = 0.55
    elif total < agg_sc:
        tier = "normal"
        tier_stake_mult = 1.0
    else:
        tier = "aggressive"
        tier_stake_mult = 1.05

    strength = str(signal.get("strength") or "Medium")
    learning_tag = LEARNING_TAGS.get(strength, "medium_micro_trade")

    return {
        "berserk_score": total,
        "micro_score_breakdown": breakdown,
        "berserk_score_tier": tier,
        "tier_stake_mult": tier_stake_mult,
        "learning_tag": learning_tag,
        "min_score_threshold": min_sc,
        "normal_score_threshold": norm_sc,
        "aggressive_score_threshold": agg_sc,
    }
