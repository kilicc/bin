"""Hunter V2 — breakout, fake breakout, liquidation, spread, spike."""
from __future__ import annotations

from typing import Any

from elite_trader.mode_engines.hunter_breakout_engine import calculate_breakout_score
from elite_trader.mode_engines.hunter_spike_engine import evaluate_spike_opportunity

STRENGTH_STAKE_MULT = {"Weak": 0.35, "Medium": 0.70, "Strong": 1.0}


def _f(profile: dict[str, Any], key: str, default: float) -> float:
    return float(profile.get(key) if profile.get(key) is not None else default)


def _side_sign(side: str) -> int:
    return 1 if str(side or "LONG").upper() == "LONG" else -1


def _aligned(delta: float, side: str) -> bool:
    if abs(delta) < 1e-9:
        return False
    return (delta > 0) == (_side_sign(side) > 0)


def spread_assessment(spread_pct: float, profile: dict[str, Any]) -> dict[str, Any]:
    sp = max(0.0, float(spread_pct))
    max_sp = _f(profile, "max_spread_pct", 0.18)
    soft = _f(profile, "soft_spread_start_pct", 0.08)
    out: dict[str, Any] = {
        "spread_pct": sp,
        "spread_risk_level": "normal",
        "score_delta": 0,
        "stake_mult": 1.0,
        "veto": False,
        "limit_order_only": False,
        "spread_penalty_applied": False,
    }
    if sp <= soft:
        return out
    if sp <= 0.14:
        out["spread_risk_level"] = "elevated"
        out["score_delta"] = -5
        out["stake_mult"] = 0.70
        out["spread_penalty_applied"] = True
        return out
    if sp <= max_sp:
        out["spread_risk_level"] = "high"
        out["score_delta"] = -10
        out["stake_mult"] = 0.45
        out["limit_order_only"] = True
        out["spread_penalty_applied"] = True
        return out
    out["spread_risk_level"] = "extreme"
    out["veto"] = True
    return out


def compute_fake_breakout_risk(
    signal: dict[str, Any],
    ctx: dict[str, Any],
    side: str,
    spread_info: dict[str, Any],
) -> tuple[float, list[str]]:
    reasons: list[str] = []
    risk = 0.0
    ch = abs(float(signal.get("change") or 0))
    vr = float(ctx.get("vol_ratio") or signal.get("vol_ratio") or 1.0)
    ob = float(ctx.get("orderbook_pressure") or signal.get("orderbook_pressure") or 0)
    sp = float(spread_info.get("spread_pct") or 0)

    if ch >= 0.25 and vr < 1.10:
        risk += 22
        reasons.append("no_volume_after_break")
    if sp > 0.10:
        risk += 15
        reasons.append("spread_wide")
    if ob != 0 and not _aligned(ob, side):
        risk += 18
        reasons.append("orderbook_withdrawal")
    if ch >= 0.35 and vr < 1.20:
        risk += 12
        reasons.append("weak_delta_support")
    wick = float(signal.get("wick_ratio") or ctx.get("wick_ratio") or 0)
    if wick > 0.55:
        risk += 14
        reasons.append("long_wick")
    if spread_info.get("spread_risk_level") in ("high", "extreme"):
        risk += 10
        reasons.append("spread_risk")
    rsi_div = bool(signal.get("rsi_divergence") or ctx.get("rsi_divergence"))
    if rsi_div:
        risk += 10
        reasons.append("rsi_divergence")
    return min(100.0, risk), reasons


def compute_liquidation_cascade_score(
    signal: dict[str, Any],
    ctx: dict[str, Any],
) -> tuple[float, dict[str, float]]:
    ch = abs(float(signal.get("change") or 0))
    vr = float(ctx.get("vol_ratio") or signal.get("vol_ratio") or 1.0)
    liq = float(ctx.get("liquidation_proxy") or signal.get("liquidation_proxy") or 0)
    funding = abs(float(ctx.get("funding_extreme") or signal.get("funding_extreme") or 0))
    oi = float(ctx.get("oi_change_pct") or signal.get("oi_change_pct") or 0)
    spread = float(ctx.get("spread_pct") or signal.get("spread_pct") or 0)
    ob = float(ctx.get("orderbook_pressure") or signal.get("orderbook_pressure") or 0)

    velocity = min(25.0, ch * 40.0)
    volume = min(25.0, max(0.0, (vr - 1.0) * 20.0))
    oi_chg = min(15.0, abs(oi) * 3.0)
    funding_sc = min(15.0, funding * 30.0)
    liq_sc = min(20.0, liq * 35.0)
    spread_behavior = 8.0 if spread <= 0.08 else (4.0 if spread <= 0.14 else 0.0)
    continuation = min(15.0, abs(ob) * 12.0 + (5.0 if ch >= 0.30 else 0))

    parts = {
        "velocity": round(velocity, 2),
        "volume": round(volume, 2),
        "oi_change": round(oi_chg, 2),
        "funding_extreme": round(funding_sc, 2),
        "liquidation_proxy": round(liq_sc, 2),
        "spread_behavior": round(spread_behavior, 2),
        "continuation_pressure": round(continuation, 2),
    }
    return min(100.0, sum(parts.values())), parts


def estimate_expected_net_usd(stake_usd: float, profile: dict[str, Any]) -> float:
    from elite_trader.fee_economics import round_trip_fee_usd

    stake = max(float(stake_usd), 1.0)
    tp_pct = float(profile.get("tp_stake_pct") or 0.0095)
    trig = float(profile.get("tp_trigger_frac") or 1.0)
    tp_usd = stake * tp_pct * trig
    fee = round_trip_fee_usd(stake, 5, fee_mult=1.0)
    return tp_usd - fee


def resolve_dynamic_tp_sl(
    profile: dict[str, Any],
    *,
    breakout_score: float,
    liq_score: float,
    fake_risk: float,
    strength: str,
) -> dict[str, float]:
    tp = _f(profile, "tp_stake_pct", 0.0095)
    sl = _f(profile, "sl_stake_pct", 0.0042)
    trig = _f(profile, "tp_trigger_frac", 1.0)
    if liq_score >= 75:
        tp = min(2.50, max(1.20, tp * 2.2))
        sl = min(0.80, max(0.50, sl * 1.35))
    elif breakout_score >= 85:
        tp = min(1.45, max(0.95, tp * 1.35))
        sl = min(0.60, max(0.42, sl * 1.15))
    elif breakout_score >= 70:
        tp = min(1.20, max(0.95, tp * 1.15))
        sl = min(0.55, max(0.42, sl * 1.05))
    elif breakout_score >= 55:
        tp = min(0.95, max(0.65, tp * 0.85))
        sl = min(0.45, max(0.32, sl * 0.90))
    if fake_risk >= 40:
        tp *= 0.85
    if strength == "Medium":
        tp *= 0.92
    return {
        "tp_stake_pct": round(tp, 5),
        "sl_stake_pct": round(sl, 5),
        "tp_trigger_frac": trig,
        "partial_tp_frac": 0.40 if liq_score >= 75 or breakout_score >= 70 else 0.0,
        "trailing_enabled": liq_score >= 75 or breakout_score >= 70,
    }


def _log_reject(signal: dict[str, Any], reason: str, meta: dict[str, Any]) -> None:
    try:
        from elite_trader.hunter_benchmark import on_hunter_reject

        on_hunter_reject(signal, reason, meta)
    except Exception:
        pass
    if reason == "fake_breakout_risk" or float(meta.get("fake_breakout_risk") or 0) >= 75:
        try:
            from elite_trader.hunter_learning import record_fake_breakout_event

            record_fake_breakout_event(signal, meta, reason)
        except Exception:
            pass


def evaluate_hunter_entry(
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
    meta: dict[str, Any] = {
        "strength_stake_mult": STRENGTH_STAKE_MULT.get(strength, 0.70),
        "spread_stake_mult": 1.0,
        "combined_stake_mult": STRENGTH_STAKE_MULT.get(strength, 0.70),
        "breakout_score": 0.0,
        "breakout_score_breakdown": {},
        "fake_breakout_risk": 0.0,
        "fake_breakout_reason": [],
        "liquidation_cascade_score": 0.0,
        "explosive_opportunity": False,
        "explosive_liquidation_opportunity": False,
        "spread_risk_level": "normal",
    }

    regime = str(ctx.get("regime") or signal.get("market_regime") or "").lower()
    if "chop" in regime and not profile.get("hunter_chop_trade_enabled", False):
        meta["hunter_chop_observation"] = True
        _log_reject(signal, "hunter_chop_observation", meta)
        return False, "hunter_chop_observation", meta

    min_spike_ch = _f(profile, "hunter_min_spike_change_pct", 0.22)
    min_spike_vol = _f(profile, "hunter_min_spike_vol_ratio", 1.25)
    br_ch = _f(profile, "hunter_breakout_change_pct", 0.30)
    br_vol = _f(profile, "hunter_breakout_vol_ratio", 1.35)
    liq_min = _f(profile, "hunter_liquidation_proxy_min", 0.30)
    min_breakout = _f(profile, "hunter_min_breakout_score", 55)

    vr = float(ctx.get("vol_ratio") or signal.get("vol_ratio") or 1.0)
    liq = float(ctx.get("liquidation_proxy") or signal.get("liquidation_proxy") or 0)

    spread = float(ctx.get("spread_pct") or signal.get("spread_pct") or 0)
    sp_info = spread_assessment(spread, profile)
    meta["spread_risk_level"] = sp_info["spread_risk_level"]
    meta["spread_stake_mult"] = sp_info["stake_mult"]
    meta["spread_penalty_applied"] = sp_info.get("spread_penalty_applied", False)
    meta["spread_pct"] = spread
    if sp_info.get("veto"):
        _log_reject(signal, "spread_risk", meta)
        return False, "spread_risk", meta

    stake_base = float(profile.get("min_stake_usd") or 160)
    tp_base = _f(profile, "tp_stake_pct", 0.0095) * _f(profile, "tp_trigger_frac", 1.0) * 100.0
    meta["spread_to_tp_ratio"] = round(spread / tp_base, 4) if tp_base > 0 else 0.0
    if tp_base > 0 and spread / tp_base > 0.55:
        _log_reject(signal, "spread_risk", meta)
        return False, "spread_risk", meta

    breakout = calculate_breakout_score(signal, ctx, profile)
    meta.update(breakout)
    breakout_score = float(meta["breakout_score"])
    signal["breakout_score"] = breakout_score

    fake_risk, fake_reasons = compute_fake_breakout_risk(signal, ctx, side, sp_info)
    meta["fake_breakout_risk"] = round(fake_risk, 2)
    meta["fake_breakout_reason"] = fake_reasons
    signal["fake_breakout_risk"] = meta["fake_breakout_risk"]

    liq_score, liq_parts = compute_liquidation_cascade_score(signal, ctx)
    meta["liquidation_cascade_score"] = round(liq_score, 2)
    meta["liquidation_cascade_breakdown"] = liq_parts
    signal["liquidation_cascade_score"] = meta["liquidation_cascade_score"]

    spike = evaluate_spike_opportunity(signal, ctx, profile, liq_score=liq_score)
    meta.update(spike)
    if spike.get("fake_spike_result"):
        meta["fake_spike_result"] = True
        _log_reject(signal, "fake_spike", meta)
        return False, "fake_spike", meta
    if spike["spike_exhaustion_score"] >= 70:
        _log_reject(signal, "spike_exhaustion", meta)
        return False, "spike_exhaustion", meta
    if spike.get("await_spike_confirmation"):
        _log_reject(signal, "spike_await_confirmation", meta)
        return False, "spike_await_confirmation", meta

    if strength == "Weak":
        if breakout_score >= min_breakout:
            meta["strength_stake_mult"] = 0.35
            meta["combined_stake_mult"] = 0.35
        else:
            from elite_trader.hunter_watchlist import add_weak_candidate

            add_weak_candidate(signal, meta)
            return False, "weak_watch_only", meta

    spike_candidate = ch >= min_spike_ch or vr >= min_spike_vol or liq >= liq_min
    breakout_candidate = (
        ch >= br_ch or vr >= br_vol or liq >= liq_min or breakout_score >= 70
    )
    if not spike_candidate:
        _log_reject(signal, "hunter_no_spike", meta)
        return False, "hunter_no_spike", meta
    if not breakout_candidate:
        _log_reject(signal, "hunter_no_breakout", meta)
        return False, "hunter_no_breakout", meta

    ob = float(ctx.get("orderbook_pressure") or signal.get("orderbook_pressure") or 0)
    flow = float(ctx.get("flow_bias") or signal.get("pool_flow_bias") or 0)
    if breakout_score >= 55 and ob != 0 and flow != 0:
        if not _aligned(ob, side) and not _aligned(flow, side):
            _log_reject(signal, "no_orderbook_support", meta)
            return False, "no_orderbook_support", meta

    if fake_risk >= 75:
        _log_reject(signal, "fake_breakout_risk", meta)
        return False, "fake_breakout_risk", meta

    if breakout_score < min_breakout:
        _log_reject(signal, "hunter_breakout_low", meta)
        return False, "hunter_breakout_low", meta

    if vr < 1.08 and breakout_score < 65:
        _log_reject(signal, "no_volume_confirmation", meta)
        return False, "no_volume_confirmation", meta

    if fake_risk >= 60 and breakout_score < 65:
        _log_reject(signal, "fake_breakout_risk", meta)
        return False, "fake_breakout_risk", meta

    meta["explosive_liquidation_opportunity"] = liq_score >= 85

    dyn = resolve_dynamic_tp_sl(
        profile,
        breakout_score=breakout_score,
        liq_score=liq_score,
        fake_risk=fake_risk,
        strength=strength,
    )
    meta["dynamic_exit"] = dyn

    stake_mult = STRENGTH_STAKE_MULT.get(strength, 0.70)
    stake_mult *= float(meta.get("tier_stake_mult") or 1.0)
    if fake_risk >= 40:
        stake_mult *= 0.60
    stake_mult *= sp_info["stake_mult"]
    meta["combined_stake_mult"] = round(stake_mult, 4)

    expected = estimate_expected_net_usd(stake_base * stake_mult, profile)
    meta["expected_net_pnl_usd"] = round(expected, 4)
    signal["expected_net_pnl"] = meta["expected_net_pnl_usd"]
    if expected <= 0:
        _log_reject(signal, "expected_net_negative", meta)
        return False, "expected_net_negative", meta

    signal["hunter_meta"] = meta
    signal["spread_risk_level"] = meta["spread_risk_level"]
    return True, "", meta


# Backward compat for tests importing compute_breakout_score
def compute_breakout_score(
    signal: dict[str, Any],
    ctx: dict[str, Any],
    side: str,
) -> tuple[float, dict[str, float]]:
    profile = ctx.get("profile") or {}
    out = calculate_breakout_score(signal, ctx, profile)
    return out["breakout_score"], out["breakout_score_breakdown"]
