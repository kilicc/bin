"""Chop V2 — failed breakout → mean reversion reversal."""
from __future__ import annotations

from typing import Any


def _f(profile: dict[str, Any], key: str, default: float) -> float:
    v = profile.get(key)
    return float(v) if v is not None else default


def detect_failed_breakout_reversal(
    signal: dict[str, Any],
    ctx: dict[str, Any],
    profile: dict[str, Any],
) -> dict[str, Any]:
    ch = float(signal.get("change") or 0)
    vr = float(ctx.get("vol_ratio") or signal.get("vol_ratio") or 1.0)
    wick = float(signal.get("wick_ratio") or ctx.get("wick_ratio") or 0)
    ob = float(ctx.get("orderbook_pressure") or signal.get("orderbook_pressure") or 0)
    range_w = float(ctx.get("range_width_pct") or signal.get("range_width_pct") or 0)
    range_high = float(ctx.get("range_high") or signal.get("range_high") or 0)
    range_low = float(ctx.get("range_low") or signal.get("range_low") or 0)
    price = float(signal.get("price") or ctx.get("price") or 0)
    close_in_range = bool(ctx.get("close_in_range") or signal.get("close_in_range"))
    delta_cont = bool(ctx.get("delta_continuation") or signal.get("delta_continuation"))

    broke_out = bool(ctx.get("range_breakout") or signal.get("range_breakout"))
    if not broke_out and range_w > 0 and price > 0:
        if abs(ch) >= range_w * 0.85:
            broke_out = True

    score = 0.0
    reasons: list[str] = []
    if broke_out:
        score += 20
        reasons.append("range_break")
    if broke_out and vr < 1.25:
        score += 18
        reasons.append("no_volume_follow")
    if close_in_range or (broke_out and abs(ch) < range_w * 0.5):
        score += 20
        reasons.append("close_back_in_range")
    if wick > 0.5:
        score += 15
        reasons.append("long_wick")
    if ob != 0 and ((ch > 0 and ob < 0) or (ch < 0 and ob > 0)):
        score += 12
        reasons.append("orderbook_no_support")
    if not delta_cont:
        score += 10
        reasons.append("delta_stalled")

    score = min(100.0, score)
    detected = score >= 55 and broke_out

    reversal_direction = ""
    if detected:
        reversal_direction = "SHORT" if ch > 0 else "LONG"

    hunter_veto = _f(profile, "chop_hunter_breakout_veto", 70)
    hunter_br = float(
        ctx.get("hunter_breakout_score")
        or signal.get("hunter_breakout_score")
        or signal.get("breakout_score")
        or 0
    )
    liq = float(ctx.get("liquidation_proxy") or signal.get("liquidation_proxy") or 0)
    spike = bool(ctx.get("spike_regime") or signal.get("spike_regime"))

    block = False
    block_reason = ""
    if hunter_br >= hunter_veto:
        block = True
        block_reason = "hunter_breakout_high"
    elif liq >= 0.45 or spike:
        block = True
        block_reason = "spike_liquidation_regime"

    return {
        "failed_breakout_detected": detected and not block,
        "reversal_score": round(score, 2),
        "reversal_direction": reversal_direction,
        "failed_breakout_reasons": reasons,
        "reversal_blocked": block,
        "reversal_block_reason": block_reason,
        "fake_breakout_to_reversal_success": None,
    }
