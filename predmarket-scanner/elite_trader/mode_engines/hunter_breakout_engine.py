"""Hunter V2 — breakout confidence score (0-100)."""
from __future__ import annotations

from typing import Any


def _f(profile: dict[str, Any], key: str, default: float) -> float:
    v = profile.get(key)
    return float(v) if v is not None else default


def _side(signal: dict[str, Any]) -> str:
    return str(signal.get("type") or signal.get("side") or "LONG").upper()


def _aligned(delta: float, side: str) -> bool:
    if abs(delta) < 1e-9:
        return False
    return (delta > 0) == (side == "LONG")


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def calculate_breakout_score(
    signal: dict[str, Any],
    ctx: dict[str, Any],
    profile: dict[str, Any],
) -> dict[str, Any]:
    side = _side(signal)
    ch = abs(float(signal.get("change") or ctx.get("change_pct") or 0))
    vr = float(ctx.get("vol_ratio") or signal.get("vol_ratio") or 1.0)
    liq = float(ctx.get("liquidation_proxy") or signal.get("liquidation_proxy") or 0)
    ob = float(ctx.get("orderbook_pressure") or signal.get("orderbook_pressure") or 0)
    flow = float(ctx.get("flow_bias") or signal.get("pool_flow_bias") or 0)
    adx = float(ctx.get("adx") or signal.get("adx") or 0)
    atr = float(ctx.get("atr_pct") or signal.get("atr_pct") or 0)
    bb_sq = float(ctx.get("bb_squeeze") or signal.get("bb_squeeze") or 0)
    body = float(ctx.get("candle_body_accel") or signal.get("candle_body_accel") or 0)
    wick = float(signal.get("wick_ratio") or ctx.get("wick_ratio") or 0)
    oi = float(ctx.get("oi_change_pct") or signal.get("oi_change_pct") or 0)
    above_vwap = ctx.get("above_vwap")

    price_expansion = _clamp(
        ch * 35.0 + min(8.0, liq * 10.0) + bb_sq * 6.0 + body * 8.0,
        0.0,
        25.0,
    )
    volume_confirmation = _clamp(
        max(0.0, (vr - 1.0) * 18.0) + (5.0 if vr >= 1.35 else 0),
        0.0,
        25.0,
    )
    volatility_expansion = _clamp(
        ch * 22.0 + atr * 40.0 + (4.0 if ch >= 0.30 else 0),
        0.0,
        20.0,
    )

    trend_alignment = 0.0
    if _aligned(flow, side):
        trend_alignment += 8.0
    if adx >= 22:
        trend_alignment += 4.0
    if ch >= 0.28:
        trend_alignment += 3.0
    if side == "LONG" and above_vwap is True:
        trend_alignment += 2.0
    elif side == "SHORT" and above_vwap is False:
        trend_alignment += 2.0
    trend_alignment = _clamp(trend_alignment, 0.0, 15.0)

    orderbook_support = _clamp(
        abs(ob) * 12.0 + (5.0 if _aligned(ob, side) else 0) + min(5.0, liq * 8.0),
        0.0,
        15.0,
    )
    if wick > 0.55:
        orderbook_support = max(0.0, orderbook_support - 4.0)
    if oi > 0.5:
        volume_confirmation = min(25.0, volume_confirmation + 2.0)

    breakdown = {
        "price_expansion": round(price_expansion, 2),
        "volume_confirmation": round(volume_confirmation, 2),
        "volatility_expansion": round(volatility_expansion, 2),
        "trend_alignment": round(trend_alignment, 2),
        "orderbook_support": round(orderbook_support, 2),
    }
    total = round(min(100.0, sum(breakdown.values())), 2)

    min_sc = _f(profile, "hunter_min_breakout_score", 55)
    strong_sc = _f(profile, "hunter_strong_breakout_score", 70)
    explosive_sc = _f(profile, "hunter_explosive_score", 85)

    tier = "observation"
    tier_stake_mult = 0.0
    if total < min_sc:
        tier = "observation"
    elif total < strong_sc:
        tier = "paper_candidate"
        tier_stake_mult = 0.70
    elif total < explosive_sc:
        tier = "strong"
        tier_stake_mult = 1.0
    else:
        tier = "explosive"
        tier_stake_mult = 1.0

    return {
        "breakout_score": total,
        "breakout_score_breakdown": breakdown,
        "breakout_tier": tier,
        "tier_stake_mult": tier_stake_mult,
        "explosive_opportunity": total >= explosive_sc,
        "min_breakout_score": min_sc,
        "strong_breakout_score": strong_sc,
        "explosive_score_threshold": explosive_sc,
    }
