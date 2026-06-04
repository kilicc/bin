"""Sentinel — quality score, execution score, spread, dynamic exit (Sentinel-only)."""
from __future__ import annotations

import time
from typing import Any


def _f(profile: dict[str, Any], key: str, default: float) -> float:
    try:
        v = profile.get(key)
        return float(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def _side(signal: dict[str, Any]) -> str:
    return str(signal.get("type") or signal.get("side") or "LONG").upper()


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _ema_alignment_score(side: str, ctx: dict[str, Any]) -> float:
    ema9 = float(ctx.get("ema9") or ctx.get("ema_9") or 0)
    ema21 = float(ctx.get("ema21") or ctx.get("ema_21") or 0)
    ema50 = float(ctx.get("ema50") or ctx.get("ema_50") or 0)
    if ema9 > 0 and ema21 > 0 and ema50 > 0:
        if side == "LONG" and ema9 > ema21 > ema50:
            return 20.0
        if side == "SHORT" and ema9 < ema21 < ema50:
            return 20.0
        if side == "LONG" and ema9 > ema21:
            return 12.0
        if side == "SHORT" and ema9 < ema21:
            return 12.0
        return 4.0
    tb = str(ctx.get("trend_bias") or "").upper()
    ch = abs(float(ctx.get("change_pct") or 0))
    if side == "LONG" and tb in ("LONG", "UP", "BULL"):
        return 14.0 + min(6.0, ch * 2)
    if side == "SHORT" and tb in ("SHORT", "DOWN", "BEAR"):
        return 14.0 + min(6.0, ch * 2)
    return 6.0


def _ema_slope_score(side: str, ctx: dict[str, Any]) -> float:
    slope = float(ctx.get("ema_slope") or ctx.get("ema_slope_pct") or 0)
    ch = float(ctx.get("change_pct") or 0)
    if slope == 0:
        slope = ch * 0.35
    if side == "LONG":
        return _clamp(8.0 + slope * 40.0, 0.0, 15.0)
    return _clamp(8.0 + (-slope) * 40.0, 0.0, 15.0)


def _vwap_alignment_score(side: str, ctx: dict[str, Any]) -> float:
    above = ctx.get("above_vwap")
    if above is None:
        tb = str(ctx.get("trend_bias") or "").upper()
        if side == "LONG" and tb in ("LONG", "UP", "BULL"):
            return 11.0
        if side == "SHORT" and tb in ("SHORT", "DOWN", "BEAR"):
            return 11.0
        return 5.0
    if side == "LONG" and above:
        return 15.0
    if side == "SHORT" and not above:
        return 15.0
    return 3.0


def _adx_score(ctx: dict[str, Any]) -> float:
    adx = float(ctx.get("adx") or 0)
    if adx >= 28:
        return 15.0
    if adx >= 22:
        return 11.0
    if adx >= 18:
        return 7.0
    vr = float(ctx.get("vol_ratio") or 1.0)
    if vr >= 1.35:
        return 8.0
    return 3.0


def _atr_score(ctx: dict[str, Any]) -> float:
    atr = float(ctx.get("atr_pct") or 0)
    if atr >= 0.08:
        return 10.0
    if atr >= 0.055:
        return 7.0
    if atr >= 0.035:
        return 4.0
    ch = abs(float(ctx.get("change_pct") or 0))
    return min(6.0, ch * 3.0)


def _volume_score(ctx: dict[str, Any]) -> float:
    vr = float(ctx.get("vol_ratio") or 1.0)
    if vr >= 1.6:
        return 10.0
    if vr >= 1.25:
        return 7.0
    if vr >= 1.05:
        return 4.0
    return 2.0


def _spread_component(spread_pct: float) -> float:
    if spread_pct <= 0.04:
        return 5.0
    if spread_pct <= 0.08:
        return 3.0
    if spread_pct <= 0.12:
        return 1.0
    return 0.0


def _slippage_component(slip: float) -> float:
    if slip <= 0.02:
        return 5.0
    if slip <= 0.04:
        return 3.0
    if slip <= 0.06:
        return 1.0
    return 0.0


def _expected_net_component(expected: float) -> float:
    if expected >= 0.8:
        return 5.0
    if expected >= 0.35:
        return 3.0
    if expected >= 0.05:
        return 1.0
    return 0.0


def calculate_sentinel_quality_score(
    signal: dict[str, Any],
    ctx: dict[str, Any],
    profile: dict[str, Any],
) -> dict[str, Any]:
    side = _side(signal)
    ch = float(signal.get("change") or ctx.get("change_pct") or 0)
    ctx = {**ctx, "change_pct": ch}
    spread_pct = float(ctx.get("spread_pct") or signal.get("spread_pct") or 0.06)
    slip = float(ctx.get("slippage_estimate") or signal.get("slippage_estimate") or 0.03)
    stake_est = float(profile.get("min_stake_usd") or 180)
    tp_base = stake_est * float(profile.get("tp_stake_pct") or 0.0095)
    expected = float(
        signal.get("expected_net_pnl")
        or ctx.get("expected_net_pnl")
        or tp_base * 0.35
        - stake_est * 0.0008
    )

    breakdown = {
        "ema_alignment": round(_ema_alignment_score(side, ctx), 2),
        "ema_slope": round(_ema_slope_score(side, ctx), 2),
        "vwap_alignment": round(_vwap_alignment_score(side, ctx), 2),
        "adx_trend_strength": round(_adx_score(ctx), 2),
        "atr_sufficient_volatility": round(_atr_score(ctx), 2),
        "volume_confirmation": round(_volume_score(ctx), 2),
        "spread_quality": round(_spread_component(spread_pct), 2),
        "slippage_quality": round(_slippage_component(slip), 2),
        "expected_net_pnl_quality": round(_expected_net_component(expected), 2),
    }
    total = round(sum(breakdown.values()), 2)
    regime = str(ctx.get("regime") or signal.get("market_regime") or "").lower()
    if "trend" in regime or "mixed" in regime:
        total = round(min(100.0, total + 3.0), 2)

    tags: list[str] = []
    if breakdown["ema_alignment"] >= 14:
        tags.append("ema_continuation")
    if breakdown["vwap_alignment"] >= 11:
        tags.append("vwap_continuation")
    if abs(ch) >= 0.35 and breakdown["adx_trend_strength"] >= 7:
        tags.append("high_quality_trend")
    if 0.12 <= abs(ch) <= 0.45 and breakdown["volume_confirmation"] >= 4:
        tags.append("high_quality_pullback")
    if breakdown["ema_slope"] >= 10:
        tags.append("trend_reclaim")
    if breakdown["vwap_alignment"] <= 4 and breakdown["ema_alignment"] >= 10:
        tags.append("trend_rejection")

    premium = total >= 88
    tier = "observation"
    if total >= 88:
        tier = "premium"
    elif total >= 75:
        tier = "high_quality"
    elif total >= 62:
        tier = "paper_candidate"
    elif total >= 55:
        tier = "watch"

    safe = round(
        min(
            100.0,
            total * 0.55
            + breakdown["spread_quality"] * 4
            + breakdown["slippage_quality"] * 4
            + (10 if expected > 0 else 0),
        ),
        2,
    )

    return {
        "sentinel_quality_score": total,
        "sentinel_quality_breakdown": breakdown,
        "sentinel_quality_tier": tier,
        "sentinel_premium_signal": premium,
        "sentinel_safe_market_score": safe,
        "sentinel_signal_tags": tags,
        "expected_net_pnl_usd": round(expected, 4),
    }


def evaluate_sentinel_spread(
    spread_pct: float,
    stake_usd: float,
    profile: dict[str, Any],
) -> dict[str, Any]:
    max_sp = _f(profile, "max_spread_pct", 0.12)
    soft = _f(profile, "soft_spread_start_pct", 0.08)
    tp_pct = float(profile.get("tp_stake_pct") or 0.0095) * float(
        profile.get("tp_trigger_frac") or 1.02
    )
    tp_usd = max(stake_usd * tp_pct, 0.5)
    ratio = spread_pct / 100.0 * stake_usd / tp_usd if tp_usd > 0 else 999.0

    meta: dict[str, Any] = {
        "spread_pct": round(spread_pct, 4),
        "spread_to_tp_ratio": round(ratio, 4),
        "spread_penalty_applied": False,
        "spread_risk_level": "ok",
        "stake_mult": 1.0,
        "prefer_limit_order": False,
        "spread_veto": False,
    }

    if spread_pct > max_sp or ratio > 0.35:
        meta["spread_risk_level"] = "veto"
        meta["spread_veto"] = True
        return meta
    if spread_pct <= 0.04:
        meta["spread_risk_level"] = "excellent"
        meta["quality_score_delta"] = 3
        return meta
    if spread_pct <= soft:
        meta["spread_risk_level"] = "acceptable"
        return meta
    meta["spread_risk_level"] = "elevated"
    meta["spread_penalty_applied"] = True
    meta["quality_score_delta"] = -8
    meta["stake_mult"] = 0.5
    meta["prefer_limit_order"] = True
    return meta


def calculate_execution_quality_score(
    signal: dict[str, Any],
    ctx: dict[str, Any],
    profile: dict[str, Any],
    quality: dict[str, Any],
) -> dict[str, Any]:
    spread_pct = float(ctx.get("spread_pct") or signal.get("spread_pct") or 0.06)
    slip = float(ctx.get("slippage_estimate") or signal.get("slippage_estimate") or 0)
    if slip <= 0:
        slip = 0.015 if spread_pct <= 0.04 else (0.022 if spread_pct <= 0.06 else 0.03)
    liq = float(ctx.get("orderbook_liquidity") or ctx.get("vol_ratio") or 1.0)
    latency = float(ctx.get("api_latency_ms") or ctx.get("latency_ms") or 200)
    stake = float(profile.get("min_stake_usd") or 180)
    tp_usd = stake * float(profile.get("tp_stake_pct") or 0.0095)
    fee_gross = tp_usd / max(stake * 0.001, 0.01)

    spread_q = _clamp(25.0 - max(0.0, spread_pct - 0.02) * 100.0, 0.0, 25.0)
    slip_q = _clamp(25.0 - slip * 280.0, 0.0, 25.0)
    liq_q = _clamp(liq * 10.0, 0.0, 20.0)
    fee_q = _clamp(min(fee_gross, 15.0) * 0.8, 0.0, 15.0)
    fill_q = 7.0 if spread_pct <= 0.08 and liq >= 1.1 else 4.0
    lat_q = 5.0 if latency <= 800 else (2.0 if latency <= 2000 else 0.0)

    total = round(spread_q + slip_q + liq_q + fee_q + fill_q + lat_q, 2)
    tier = "block"
    if total >= 90:
        tier = "premium"
    elif total >= 80:
        tier = "normal"
    elif total >= 70:
        tier = "low_stake"

    prefer_market = (
        abs(float(signal.get("change") or 0)) >= 0.35
        and spread_pct <= 0.06
        and slip <= 0.03
        and liq >= 1.2
    )

    return {
        "sentinel_execution_quality_score": total,
        "execution_quality_breakdown": {
            "spread_quality": round(spread_q, 2),
            "slippage_estimate_quality": round(slip_q, 2),
            "orderbook_liquidity": round(liq_q, 2),
            "fee_gross_projection": round(fee_q, 2),
            "fill_probability": round(fill_q, 2),
            "latency_health": round(lat_q, 2),
        },
        "execution_quality_tier": tier,
        "prefer_market_order": prefer_market,
        "prefer_limit_order": not prefer_market or spread_pct > 0.06,
    }


def assess_sentinel_risk_off(
    signal: dict[str, Any],
    ctx: dict[str, Any],
    profile: dict[str, Any],
    quality: dict[str, Any],
    execution: dict[str, Any],
) -> dict[str, Any]:
    reasons: list[str] = []
    spread_pct = float(ctx.get("spread_pct") or signal.get("spread_pct") or 0)
    latency = float(ctx.get("api_latency_ms") or ctx.get("latency_ms") or 0)
    safe = float(quality.get("sentinel_safe_market_score") or 0)
    exec_sc = float(execution.get("sentinel_execution_quality_score") or 0)

    if ctx.get("news_shock") or signal.get("news_shock"):
        reasons.append("news_shock")
    if spread_pct > _f(profile, "max_spread_pct", 0.12):
        reasons.append("spread_spike")
    if latency >= 2500:
        reasons.append("api_latency")
    if ctx.get("btc_reversal") or signal.get("btc_reversal"):
        reasons.append("btc_reversal")
    if ctx.get("correlation_dump") or signal.get("correlation_dump"):
        reasons.append("correlation_dump")
    if ctx.get("trend_break") or signal.get("trend_break"):
        reasons.append("trend_break")
    fee_gross = float(ctx.get("fee_gross_ratio") or signal.get("fee_gross_ratio") or 0)
    if fee_gross >= 0.55:
        reasons.append("fee_gross_deterioration")
    if safe < 40:
        reasons.append("safe_market_low")
    if exec_sc < 55:
        reasons.append("execution_quality_low")
    if float(quality.get("expected_net_pnl_usd") or 0) < 0:
        reasons.append("expected_net_negative")

    risk_off = bool(reasons)
    mode = "normal"
    if risk_off:
        if ctx.get("news_shock") or signal.get("news_shock"):
            mode = "paper_only"
        elif len(reasons) >= 2:
            mode = "stop_new_entries"
        else:
            mode = "cautious"
    if spread_pct > 0.10 and mode == "normal":
        mode = "reduce_size"
    if safe < 50 and mode not in ("stop_new_entries", "paper_only"):
        mode = "reduce_size"

    return {
        "sentinel_risk_off": risk_off,
        "risk_off_reason": ",".join(reasons) if reasons else "",
        "avoid_market_now": risk_off,
        "recommended_risk_mode": mode,
    }


def resolve_sentinel_stake_mult(
    strength: str,
    quality: dict[str, Any],
    spread_meta: dict[str, Any],
    profile: dict[str, Any],
) -> float:
    base = float(profile.get("entry_stake_mult") or 0.9)
    q = float(quality.get("sentinel_quality_score") or 0)
    sm = 1.0 if strength == "Strong" else float(profile.get("medium_stake_multiplier") or 0.60)
    sm *= float(spread_meta.get("stake_mult") or 1.0)
    if q >= 88:
        sm *= float(profile.get("strong_stake_multiplier") or 1.0)
    elif q < 68:
        sm *= 0.85
    return round(base * sm, 4)


def resolve_sentinel_dynamic_exit(
    stake_usd: float,
    quality_score: float,
    profile: dict[str, Any],
) -> dict[str, Any]:
    base_tp = float(profile.get("tp_stake_pct") or 0.0095)
    base_sl = float(profile.get("sl_stake_pct") or 0.0042)
    trig = float(profile.get("tp_trigger_frac") or 1.02)

    if quality_score >= 88:
        tp_pct = min(base_tp * 1.60, max(base_tp * 1.20, base_tp * 1.35))
        sl_pct = min(base_sl * 0.60, max(base_sl * 0.45, base_sl * 1.12))
    elif quality_score >= 75:
        tp_pct = min(base_tp * 1.20, max(base_tp * 0.85, base_tp * 1.05))
        sl_pct = min(base_sl * 0.50, max(base_sl * 0.35, base_sl * 0.95))
    elif quality_score >= 62:
        tp_pct = min(base_tp * 0.85, max(base_tp * 0.60, base_tp * 0.72))
        sl_pct = min(base_sl * 0.42, max(base_sl * 0.28, base_sl * 0.78))
    else:
        tp_pct = base_tp * 0.60
        sl_pct = base_sl * 0.28

    rr = (tp_pct * trig) / max(sl_pct, 1e-9)
    if rr < 1.5:
        tp_pct = sl_pct * 1.5 / trig

    return {
        "tp_stake_pct": round(tp_pct, 6),
        "sl_stake_pct": round(sl_pct, 6),
        "tp_trigger_frac": trig,
        "partial_tp_frac": 0.40,
        "trailing_enabled": quality_score >= 75,
        "momentum_weak_exit": True,
        "vwap_cross_exit": True,
        "rr_ratio": round((tp_pct * trig) / sl_pct, 3),
    }
