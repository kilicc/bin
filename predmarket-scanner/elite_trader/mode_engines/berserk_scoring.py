"""Berserk V2 — micro-scalp skor, spread, slippage, fee survival, dynamic exit."""
from __future__ import annotations

import os
from typing import Any

from elite_trader.berserk_fee_survival import assess_fee_survival
from elite_trader.mode_engines.berserk_micro_engine import calculate_micro_score

SPREAD_SOFT_START = 0.06
SPREAD_MEDIUM_END = 0.10
SPREAD_HIGH_END = 0.12


def _side_sign(side: str) -> int:
    return 1 if str(side or "LONG").upper() == "LONG" else -1


def _aligned(delta: float, side: str) -> bool:
    if abs(delta) < 1e-9:
        return False
    return (delta > 0) == (_side_sign(side) > 0)


def min_move_pct(profile: dict[str, Any]) -> float:
    return float(profile.get("berserk_min_move_pct") or 0.09)


def strength_stake_mult(strength: str, profile: dict[str, Any]) -> float:
    key = {
        "Weak": "weak_stake_multiplier",
        "Medium": "medium_stake_multiplier",
        "Strong": "strong_stake_multiplier",
    }.get(str(strength), "medium_stake_multiplier")
    defaults = {"Weak": 0.45, "Medium": 0.75, "Strong": 1.0}
    return float(profile.get(key) or defaults.get(str(strength), 0.75))


def spread_assessment(
    spread_pct: float,
    profile: dict[str, Any],
    *,
    stake_usd: float = 120.0,
) -> dict[str, Any]:
    sp = max(0.0, float(spread_pct))
    max_sp = float(profile.get("max_spread_pct") or 0.12)
    soft = float(profile.get("soft_spread_start_pct") or SPREAD_SOFT_START)
    tp_pct = float(profile.get("tp_stake_pct") or 0.0042) * float(
        profile.get("tp_trigger_frac") or 0.99
    )
    tp_usd = max(stake_usd * tp_pct, 0.5)
    ratio = (sp / 100.0 * stake_usd) / tp_usd if tp_usd > 0 else 999.0

    out: dict[str, Any] = {
        "spread_pct": round(sp, 4),
        "spread_to_tp_ratio": round(ratio, 4),
        "spread_penalty_applied": False,
        "spread_risk_level": "none",
        "score_delta": 0,
        "stake_mult": 1.0,
        "veto": False,
        "limit_order_only": False,
    }
    if sp > max_sp or ratio > 0.35:
        out["spread_risk_level"] = "veto"
        out["veto"] = True
        return out
    if sp <= soft:
        return out
    if sp <= SPREAD_MEDIUM_END:
        out["spread_risk_level"] = "low"
        out["spread_penalty_applied"] = True
        out["score_delta"] = -4
        out["stake_mult"] = 0.70
        return out
    if sp <= SPREAD_HIGH_END:
        out["spread_risk_level"] = "medium"
        out["spread_penalty_applied"] = True
        out["score_delta"] = -9
        out["stake_mult"] = 0.45
        out["limit_order_only"] = True
        return out
    out["spread_risk_level"] = "high"
    out["score_delta"] = -12
    out["stake_mult"] = 0.35
    return out


def evaluate_slippage(
    slippage_pct: float,
    stake_usd: float,
    profile: dict[str, Any],
) -> dict[str, Any]:
    slip = max(0.0, float(slippage_pct))
    tp_pct = float(profile.get("tp_stake_pct") or 0.0042) * float(
        profile.get("tp_trigger_frac") or 0.99
    )
    tp_usd = max(stake_usd * tp_pct, 0.5)
    slip_usd = stake_usd * slip / 100.0
    ratio = slip_usd / tp_usd if tp_usd > 0 else 999.0
    out: dict[str, Any] = {
        "slippage_pct": round(slip, 4),
        "slippage_to_tp_ratio": round(ratio, 4),
        "slippage_damage_score": 0.0,
        "stake_mult": 1.0,
        "veto": False,
    }
    if ratio <= 0.30:
        return out
    if ratio <= 0.50:
        out["slippage_damage_score"] = round(ratio, 4)
        out["stake_mult"] = 0.65
        return out
    out["slippage_damage_score"] = round(ratio, 4)
    out["veto"] = True
    return out


def intelligence_adjustments(
    signal: dict[str, Any],
    side: str,
    ctx: dict[str, Any],
) -> dict[str, Any]:
    score_delta = 0
    stake_mult = 1.0
    flow = float(ctx.get("flow_bias") or signal.get("pool_flow_bias") or 0)
    ob = float(ctx.get("orderbook_pressure") or signal.get("orderbook_pressure") or 0)
    cross = float(
        ctx.get("cross_exchange_delta")
        or signal.get("pool_cross_px_delta_pct")
        or 0
    )
    vol_p = float(ctx.get("volume_pressure") or signal.get("volume_pressure") or 0)
    if vol_p == 0:
        vr = float(ctx.get("vol_ratio") or signal.get("vol_ratio") or 1.0)
        vol_p = max(0.0, vr - 1.0)
    news = str(ctx.get("news_sentiment") or signal.get("pool_news_sentiment") or "").lower()

    if _aligned(flow, side):
        score_delta += 4
    elif flow != 0 and not _aligned(flow, side):
        stake_mult *= 0.60
    if _aligned(ob, side):
        score_delta += 4
    elif ob != 0 and not _aligned(ob, side):
        stake_mult *= 0.55
    if _aligned(cross, side):
        score_delta += 3
    if _aligned(vol_p, side):
        score_delta += 3
    elif vol_p != 0 and not _aligned(vol_p, side):
        stake_mult *= 0.70
    if news in ("uncertain", "bearish", "risky") and side == "LONG":
        score_delta -= 3
    if news in ("uncertain", "bullish", "risky") and side == "SHORT":
        score_delta -= 3

    return {"score_delta": score_delta, "stake_mult": stake_mult}


def estimate_expected_net_usd(
    stake_usd: float,
    profile: dict[str, Any],
    *,
    tp_bump: float = 0.0,
) -> float:
    from elite_trader.fee_economics import round_trip_fee_usd

    stake = max(float(stake_usd), 1.0)
    tp_pct = float(profile.get("tp_stake_pct") or 0.0042) + tp_bump
    trig = float(profile.get("tp_trigger_frac") or 0.99)
    tp_usd = stake * tp_pct * trig
    fee = round_trip_fee_usd(stake, 5, fee_mult=1.0)
    return tp_usd - fee


def weak_signal_ok(
    signal: dict[str, Any],
    side: str,
    ctx: dict[str, Any],
    profile: dict[str, Any],
    spread_info: dict[str, Any],
) -> tuple[bool, str]:
    if spread_info.get("spread_risk_level") not in ("none", "low"):
        return False, "berserk_weak_spread"
    vr = float(ctx.get("vol_ratio") or signal.get("vol_ratio") or 1.0)
    if vr < 1.08 and float(ctx.get("volume_pressure") or 0) < 0.05:
        return False, "berserk_weak_no_volume"
    ob = float(ctx.get("orderbook_pressure") or signal.get("orderbook_pressure") or 0)
    flow = float(ctx.get("flow_bias") or signal.get("pool_flow_bias") or 0)
    if not _aligned(ob, side) and not _aligned(flow, side):
        return False, "berserk_weak_pressure"
    est_stake = float(profile.get("min_stake_usd") or 120) * strength_stake_mult("Weak", profile)
    est_stake *= float(spread_info.get("stake_mult") or 1.0)
    if estimate_expected_net_usd(est_stake, profile) <= 0:
        return False, "berserk_weak_net_negative"
    return True, ""


def resolve_berserk_dynamic_exit(
    score: float,
    momentum: float,
    spread_pct: float,
    profile: dict[str, Any],
    *,
    tp_bump: float = 0.0,
) -> dict[str, Any]:
    base_tp = float(profile.get("tp_stake_pct") or 0.0042) + tp_bump
    base_sl = float(profile.get("sl_stake_pct") or 0.0024)
    trig = float(profile.get("tp_trigger_frac") or 0.99)

    tp_pct = base_tp
    sl_pct = base_sl
    if momentum > 0.15 or score >= float(profile.get("berserk_aggressive_score") or 75):
        tp_pct *= 1.12
    elif momentum < -0.05:
        tp_pct *= 0.88
        sl_pct *= 0.92
    if spread_pct > float(profile.get("soft_spread_start_pct") or 0.06):
        tp_pct *= 0.95

    return {
        "tp_stake_pct": round(tp_pct, 6),
        "sl_stake_pct": round(sl_pct, 6),
        "tp_trigger_frac": trig,
        "partial_tp_frac": 0.0,
        "trailing_enabled": False,
        "momentum_weak_exit": momentum < -0.08,
        "spread_exit_watch": spread_pct > 0.08,
        "spike_enabled": bool(profile.get("spike_enabled", True)),
        "stale_enabled": bool(profile.get("stale_enabled", True)),
    }


def evaluate_berserk_entry(
    signal: dict[str, Any],
    ctx: dict[str, Any],
    profile: dict[str, Any],
    *,
    edge: float,
    formula: float,
) -> tuple[bool, str, dict[str, Any]]:
    side = str(signal.get("type") or "LONG")
    strength = str(signal.get("strength") or "Medium")
    ch = abs(float(signal.get("change") or 0))
    stake_base = float(profile.get("min_stake_usd") or 120)

    meta: dict[str, Any] = {
        "berserk_score": 0.0,
        "spread_risk_level": "none",
        "strength_stake_mult": strength_stake_mult(strength, profile),
        "spread_stake_mult": 1.0,
        "intel_stake_mult": 1.0,
        "slippage_stake_mult": 1.0,
        "tier_stake_mult": 1.0,
        "fee_stake_mult": 1.0,
        "limit_order_only": False,
        "cooldown_reject": False,
        "cooldown_remaining_sec": 0.0,
        "learning_tag": "",
    }

    if ch < min_move_pct(profile):
        return False, "berserk_min_move", meta

    spread = float(ctx.get("spread_pct") or signal.get("spread_pct") or 0)
    sp_info = spread_assessment(spread, profile, stake_usd=stake_base)
    meta.update(
        {
            "spread_risk_level": sp_info["spread_risk_level"],
            "spread_stake_mult": sp_info["stake_mult"],
            "spread_to_tp_ratio": sp_info.get("spread_to_tp_ratio"),
            "spread_penalty_applied": sp_info.get("spread_penalty_applied"),
            "limit_order_only": bool(sp_info.get("limit_order_only")),
        }
    )
    if sp_info.get("veto"):
        return False, "berserk_spread_extreme", meta

    slip_pct = float(ctx.get("slippage_estimate") or signal.get("slippage_estimate") or 0.02)
    slip_info = evaluate_slippage(slip_pct, stake_base, profile)
    meta["slippage_damage_score"] = slip_info.get("slippage_damage_score", 0)
    meta["slippage_stake_mult"] = slip_info.get("stake_mult", 1.0)
    if slip_info.get("veto"):
        return False, "berserk_slippage_veto", meta

    micro = calculate_micro_score(signal, ctx, profile)
    meta.update(micro)
    score = float(micro["berserk_score"])
    min_sc = float(profile.get("berserk_min_score") or 45) + int(
        (assess_fee_survival(profile).get("fee_min_score_boost") or 0)
    )
    fee_state = assess_fee_survival(profile)
    meta.update(fee_state)
    meta["fee_stake_mult"] = fee_state.get("fee_stake_mult", 1.0)
    if fee_state.get("fee_prefer_limit"):
        meta["limit_order_only"] = True
    if fee_state.get("fee_market_disabled"):
        meta["prefer_limit_order"] = True

    intel = intelligence_adjustments(signal, side, ctx)
    meta["intel_stake_mult"] = intel["stake_mult"]
    score += sp_info["score_delta"] + intel["score_delta"]
    score = max(0.0, min(100.0, score))
    meta["berserk_score"] = round(score, 2)
    signal["berserk_score"] = meta["berserk_score"]
    signal["spread_risk_level"] = meta["spread_risk_level"]
    signal["learning_tag"] = meta.get("learning_tag")

    if score < min_sc:
        return False, "berserk_score_low", meta

    if strength == "Weak":
        ok_w, w_reason = weak_signal_ok(signal, side, ctx, profile, sp_info)
        if not ok_w:
            return False, w_reason, meta

    tier_mult = float(micro.get("tier_stake_mult") or 1.0)
    if micro.get("berserk_score_tier") == "paper_trial":
        tier_mult = min(tier_mult, 0.55)
    meta["tier_stake_mult"] = tier_mult

    combined = (
        meta["strength_stake_mult"]
        * meta["spread_stake_mult"]
        * meta["intel_stake_mult"]
        * meta["slippage_stake_mult"]
        * meta["tier_stake_mult"]
        * meta["fee_stake_mult"]
    )
    meta["combined_stake_mult"] = round(combined, 4)

    tp_bump = float(fee_state.get("fee_tp_min_bump") or 0)
    est = estimate_expected_net_usd(stake_base * combined, profile, tp_bump=tp_bump)
    meta["expected_net_pnl_usd"] = round(est, 4)
    signal["expected_net_pnl"] = meta["expected_net_pnl_usd"]
    if est <= 0:
        return False, "berserk_expected_net_negative", meta

    momentum = float(ctx.get("micro_accel") or ch * 0.4)
    meta["berserk_dynamic_exit"] = resolve_berserk_dynamic_exit(
        score, momentum, spread, profile, tp_bump=tp_bump
    )
    return True, "", meta


def resolve_min_stake(
    profile: dict[str, Any],
    *,
    paper: bool,
    env_min: float,
    binance_min: float = 0.0,
    strength_mult: float = 1.0,
) -> tuple[float, str]:
    try:
        env_max = float(os.getenv("ELITE_MAX_STAKE_USD", "0") or 0)
    except ValueError:
        env_max = 0.0
    if env_min > 0 and env_max > 0 and abs(env_max - env_min) < 1.0:
        return float(env_min), "fixed_env_stake"
    mode_min = float(profile.get("min_stake_usd") or 120)
    if paper:
        sm = max(0.35, min(1.05, float(strength_mult or 1.0)))
        scaled = mode_min * sm
        floor = max(float(os.getenv("ELITE_MIN_STAKE_FLOOR_USD", "80") or 80), scaled)
        return floor, "mode_profile_paper_scaled"
    candidates = [(mode_min, "mode_profile"), (env_min, "global_env")]
    if binance_min > 0:
        candidates.append((binance_min, "binance_rule"))
    best = max(candidates, key=lambda x: x[0])
    return best[0], best[1]
