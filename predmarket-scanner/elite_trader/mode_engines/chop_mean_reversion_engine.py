"""Chop V2 — mean reversion opportunity score."""
from __future__ import annotations

from typing import Any


def _side(signal: dict[str, Any]) -> str:
    return str(signal.get("type") or signal.get("side") or "LONG").upper()


def _f(profile: dict[str, Any], key: str, default: float) -> float:
    v = profile.get(key)
    return float(v) if v is not None else default


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def calculate_mean_reversion_score(
    signal: dict[str, Any],
    ctx: dict[str, Any],
    profile: dict[str, Any],
) -> dict[str, Any]:
    side = _side(signal)
    ch = float(signal.get("change") or 0)
    vr = float(ctx.get("vol_ratio") or signal.get("vol_ratio") or 1.0)
    rsi7 = float(ctx.get("rsi7") or signal.get("rsi7") or 50)
    wick = float(signal.get("wick_ratio") or ctx.get("wick_ratio") or 0)
    spread = float(ctx.get("spread_pct") or signal.get("spread_pct") or 0)
    adx = float(ctx.get("adx") or signal.get("adx") or 25)
    range_low_reject = bool(ctx.get("range_low_rejection") or signal.get("range_low_rejection"))
    range_high_reject = bool(ctx.get("range_high_rejection") or signal.get("range_high_rejection"))
    bb_lower = bool(ctx.get("bb_lower_rejection") or signal.get("bb_lower_rejection"))
    bb_upper = bool(ctx.get("bb_upper_rejection") or signal.get("bb_upper_rejection"))
    vwap_return = bool(ctx.get("vwap_return_prob") or signal.get("vwap_return_prob"))
    liq_sweep = bool(ctx.get("liquidity_sweep") or signal.get("liquidity_sweep"))
    long_lower_wick = bool(signal.get("long_lower_wick") or ctx.get("long_lower_wick"))
    long_upper_wick = bool(signal.get("long_upper_wick") or ctx.get("long_upper_wick"))

    range_rejection = 0.0
    if side == "LONG":
        if range_low_reject or bb_lower or long_lower_wick or (ch < -0.05 and wick > 0.4):
            range_rejection = 22.0
        elif ch < 0:
            range_rejection = 12.0
    else:
        if range_high_reject or bb_upper or long_upper_wick or (ch > 0.05 and wick > 0.4):
            range_rejection = 22.0
        elif ch > 0:
            range_rejection = 12.0

    vwap_prob = 0.0
    if vwap_return or abs(ch) < 0.15:
        vwap_prob = 14.0
    if side == "LONG" and ch < 0:
        vwap_prob += 4.0
    elif side == "SHORT" and ch > 0:
        vwap_prob += 4.0
    vwap_prob = _clamp(vwap_prob, 0.0, 20.0)

    rsi_rev = 0.0
    if side == "LONG" and rsi7 <= 28:
        rsi_rev = min(15.0, 10.0 + (28 - rsi7) * 0.4)
    elif side == "SHORT" and rsi7 >= 72:
        rsi_rev = min(15.0, 10.0 + (rsi7 - 72) * 0.4)

    wick_rej = 0.0
    if wick >= 0.45:
        wick_rej = min(15.0, wick * 20.0)
    if side == "LONG" and long_lower_wick:
        wick_rej = max(wick_rej, 12.0)
    if side == "SHORT" and long_upper_wick:
        wick_rej = max(wick_rej, 12.0)

    vol_beh = 0.0
    if 0.9 <= vr <= 1.4:
        vol_beh = 10.0
    elif vr < 1.6:
        vol_beh = 6.0
    if liq_sweep:
        vol_beh = min(15.0, vol_beh + 5.0)

    spread_q = 10.0 if spread <= 0.05 else (6.0 if spread <= 0.09 else (2.0 if spread <= 0.12 else 0.0))

    if adx > 30:
        range_rejection = max(0.0, range_rejection - 8.0)

    breakdown = {
        "range_rejection": round(range_rejection, 2),
        "VWAP_return_probability": round(vwap_prob, 2),
        "RSI_reversal": round(rsi_rev, 2),
        "wick_rejection": round(wick_rej, 2),
        "volume_behavior": round(vol_beh, 2),
        "spread_quality": round(spread_q, 2),
    }
    total = round(min(100.0, sum(breakdown.values())), 2)
    min_sc = _f(profile, "chop_mr_min_score", 65)

    return {
        "mean_reversion_score": total,
        "mean_reversion_breakdown": breakdown,
        "mean_reversion_candidate": total >= min_sc,
        "chop_mr_min_score": min_sc,
    }
