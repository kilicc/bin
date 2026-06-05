"""
Evrim — 0-100 hybrid trade skoru (7 bileşen).

Yalnızca evrim; diğer modlara dokunmaz.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from elite_trader.evrim_opportunity import (
    MODE_ID,
    _fetch_context,
    _loss_streak_ban,
    _record_rejection,
)
from elite_trader.fee_economics import net_tp_target_usd, round_trip_fee_usd
from elite_trader.panel_strategy import stake_targets

COMPONENT_MAX = {
    "price_action": 25,
    "volume_delta": 20,
    "volatility_atr": 15,
    "trend_ema": 15,
    "orderbook_liquidity": 10,
    "news_whale_risk": 10,
    "execution_quality": 5,
}

TIER_STAKE_MULT = {
    "none": 0.0,
    "normal": 1.0,
    "aggressive": 1.15,
    "max_aggressive": 1.30,
}


@dataclass
class HybridDecision:
    ok: bool
    total_score: float
    tier: str
    components: dict[str, float] = field(default_factory=dict)
    reason_enter: str = ""
    reason_skip: str = ""
    expected_net_pnl_usd: float = 0.0
    stake_mult: float = 1.0
    context: dict[str, Any] = field(default_factory=dict)
    hard_veto: str = ""
    chop_mode: bool = False
    mtf_notes: list[str] = field(default_factory=list)


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _tier_from_score(total: float, min_score: float) -> str:
    if total < min_score:
        return "none"
    if total >= 85:
        return "max_aggressive"
    if total >= 75:
        return "aggressive"
    if total >= 65:
        return "normal"
    if total >= min_score:
        return "normal"
    return "none"


def _load_training_rules() -> dict[str, Any]:
    try:
        from elite_trader.evrim_training import load_training_state

        return load_training_state()
    except Exception:
        return {}


def _score_price_action(
    signal: dict[str, Any],
    side: str,
    ctx: dict[str, Any],
    profile: dict[str, Any],
) -> tuple[float, list[str], Any | None, float]:
    """Returns score, notes, PaAnalysis|None, pa_stake_mult."""
    try:
        from elite_trader.evrim_price_action import score_component

        score, pa, notes = score_component(
            signal, side, ctx, profile, max_points=COMPONENT_MAX["price_action"]
        )
        stake = float(pa.stake_mult) if pa else 1.0
        return score, notes, pa, stake
    except Exception:
        pass
    ch = abs(float(signal.get("change") or 0))
    strength = str(signal.get("strength") or "Medium")
    move = ch / 100.0
    raw = min(0.35, move * 40.0)
    s = _clamp(raw / 0.35, 0, 1) * 14
    notes: list[str] = []
    if strength == "Strong":
        s += 6
    elif strength == "Medium":
        s += 3
    d3 = str(ctx.get("direction_3") or "none")
    if side == "LONG" and d3 == "up":
        s += 4
        notes.append("3m_up")
    elif side == "SHORT" and d3 == "down":
        s += 4
        notes.append("3m_down")
    elif d3 != "none":
        s -= 3
    regime = str(ctx.get("regime") or "")
    if "trend" in regime:
        if (side == "LONG" and "up" in regime) or (side == "SHORT" and "down" in regime):
            s += 2
    return _clamp(s, 0, COMPONENT_MAX["price_action"]), notes, None, 1.0


def _score_volume(ctx: dict[str, Any], profile: dict[str, Any]) -> float:
    vol_ratio = float(ctx.get("vol_ratio") or 0)
    target = float(profile.get("evrim_vol_mult") or 1.8)
    if vol_ratio >= target * 1.4:
        return 20.0
    if vol_ratio >= target:
        return 16.0
    if vol_ratio >= target * 0.85:
        return 10.0
    if vol_ratio >= 1.2:
        return 6.0
    return _clamp((vol_ratio / max(target, 0.5)) * 12, 0, 20)


def _score_volatility(ctx: dict[str, Any], profile: dict[str, Any]) -> float:
    atr = float(ctx.get("atr_pct") or 0)
    atr_min = float(profile.get("evrim_atr_min_pct") or 0.055)
    if ctx.get("chop"):
        return 2.0
    if atr >= atr_min * 2:
        return 15.0
    if atr >= atr_min:
        return 11.0
    if atr >= atr_min * 0.7:
        return 6.0
    return 0.0


def _score_trend(side: str, ctx: dict[str, Any]) -> float:
    s = 5.0
    trend = str(ctx.get("ema_trend") or "")
    if side == "LONG" and trend == "up":
        s += 7
    elif side == "SHORT" and trend == "down":
        s += 7
    elif trend == "flat":
        s += 2
    else:
        s -= 4
    btc = str(ctx.get("btc_regime") or "")
    if btc == "chop":
        s -= 3
    elif "trend" in btc:
        if (side == "LONG" and "up" in btc) or (side == "SHORT" and "down" in btc):
            s += 3
    d3 = str(ctx.get("direction_3") or "none")
    if side == "LONG" and d3 == "up":
        s += 3
    elif side == "SHORT" and d3 == "down":
        s += 3
    return _clamp(s, 0, COMPONENT_MAX["trend_ema"])


def _score_orderbook(ctx: dict[str, Any], profile: dict[str, Any]) -> float:
    spread = float(ctx.get("spread_pct") or 0.05)
    stake = float(profile.get("min_stake_usd") or 140)
    tp_usd, _ = stake_targets(stake, MODE_ID)
    spread_frac = float(profile.get("evrim_spread_tp_frac") or 0.18)
    price = float(ctx.get("price") or 1)
    spread_cost = price * spread / 100.0 * stake
    tp_ref = max(tp_usd, 0.5)
    ratio = spread_cost / tp_ref if tp_ref > 0 else 1.0
    if ratio <= spread_frac * 0.5:
        return 10.0
    if ratio <= spread_frac:
        return 7.0
    if ratio <= spread_frac * 1.5:
        return 4.0
    return 1.0


def _score_news_whale(
    symbol: str, ctx: dict[str, Any], profile: dict[str, Any]
) -> float:
    rules = _load_training_rules()
    risk_syms = set(rules.get("risk_symbols") or [])
    boost_syms = set(rules.get("boost_symbols") or [])
    if symbol in risk_syms:
        return 0.0
    s = 6.0
    if symbol in boost_syms:
        s += 2
    funding = float(ctx.get("funding_abs") or 0)
    funding_max = float(profile.get("evrim_funding_max") or 0.0008)
    if funding > funding_max:
        s -= 5
    elif funding < funding_max * 0.5:
        s += 2
    vol_ratio = float(ctx.get("vol_ratio") or 0)
    if vol_ratio >= 2.5:
        s += 2
    last = ctx.get("last_candle") or {}
    if last:
        o, h, l, c = (
            float(last.get("o", 0)),
            float(last.get("h", 0)),
            float(last.get("l", 0)),
            float(last.get("c", 0)),
        )
        body = abs(c - o)
        rng = max(h - l, 1e-12)
        if body / rng > 0.65 and vol_ratio >= 2.0:
            s += 1
    return _clamp(s, 0, COMPONENT_MAX["news_whale_risk"])


def _score_execution(
    profile: dict[str, Any], leverage: int = 5
) -> tuple[float, float]:
    stake = float(profile.get("min_stake_usd") or 140)
    net_tp = net_tp_target_usd(stake, MODE_ID)
    rt_fee = round_trip_fee_usd(stake, leverage)
    expected = round(net_tp - rt_fee, 4)
    if expected >= 1.0:
        return 5.0, expected
    if expected >= 0.35:
        return 3.5, expected
    if expected >= 0:
        return 1.5, expected
    return 0.0, expected


def evaluate(
    signal: dict[str, Any],
    profile: dict[str, Any],
    *,
    side: str | None = None,
    execution_path: str = "paper",
    log_decision: bool = True,
    ctx_override: dict[str, Any] | None = None,
) -> HybridDecision:
    symbol = str(signal.get("symbol") or "")
    side = side or str(signal.get("type") or "LONG")
    prof_work = dict(profile)
    try:
        from elite_trader.evrim_risk_policy import recovery_runtime_patch

        prof_work.update(recovery_runtime_patch(prof_work))
    except Exception:
        pass
    profile = prof_work
    min_score = float(profile.get("evrim_min_total_score") or 55)
    ban_min = int(profile.get("evrim_loss_ban_min") or 20)
    block_weak = bool(profile.get("entry_block_weak", True))
    strength = str(signal.get("strength") or "Medium")

    if not symbol:
        d = HybridDecision(
            ok=False,
            total_score=0,
            tier="none",
            reason_skip="no_symbol",
            hard_veto="no_symbol",
        )
        if log_decision:
            _log(d, signal, execution_path)
        return d

    if block_weak and strength == "Weak":
        d = HybridDecision(
            ok=False,
            total_score=0,
            tier="none",
            reason_skip="weak_signal",
            hard_veto="weak_signal",
        )
        if log_decision:
            _log(d, signal, execution_path)
        return d

    ban = _loss_streak_ban(symbol, ban_min)
    if ban:
        _record_rejection(ban, {})
        d = HybridDecision(
            ok=False,
            total_score=0,
            tier="none",
            reason_skip=ban,
            hard_veto=ban,
        )
        if log_decision:
            _log(d, signal, execution_path)
        return d

    ctx = dict(ctx_override) if ctx_override else _fetch_context(symbol)
    if not ctx.get("ok"):
        ch = abs(float(signal.get("change") or 0))
        if ch >= 0.38 and strength in ("Strong", "Medium"):
            ctx = {
                "ok": True,
                "regime": "mixed",
                "vol_ratio": 1.5,
                "atr_pct": 0.08,
                "spread_pct": 0.05,
                "funding_abs": 0,
                "ema_trend": "flat",
                "direction_3": "none",
                "btc_regime": "unknown",
                "chop": False,
                "price": 1.0,
                "fallback": True,
            }
        else:
            _record_rejection("market_data", ctx)
            d = HybridDecision(
                ok=False,
                total_score=0,
                tier="none",
                reason_skip="market_data",
                context=ctx,
                hard_veto="market_data",
            )
            if log_decision:
                _log(d, signal, execution_path)
            return d

    if profile.get("evrim_market_radar_enabled", True):
        try:
            from elite_trader.evrim_market_radar import evaluate_emergency
            from elite_trader.evrim_risk_policy import assess_spread_risk

            spread_pre = float(ctx.get("spread_pct") or 0.05)
            spread_assess_pre = assess_spread_risk(symbol, spread_pre, ctx, profile)
            ctx["spread_risk"] = spread_assess_pre
            emerg_pre = evaluate_emergency(
                profile,
                ctx,
                {"spread_pct": spread_pre, "api_latency_ms": 0},
            )
            if emerg_pre.get("block_new_entries") and str(
                emerg_pre.get("level") or ""
            ) in ("dd_halt", "api_slow", "spread_halt"):
                if spread_assess_pre.get("hard_veto") or emerg_pre.get("level") != "spread_halt":
                    reason = str(emerg_pre.get("level") or "radar_emergency")
                    _record_rejection(reason, ctx)
                    d = HybridDecision(
                        ok=False,
                        total_score=0,
                        tier="none",
                        reason_skip=reason,
                        context=ctx,
                        hard_veto=reason,
                    )
                    if log_decision:
                        _log(d, signal, execution_path)
                    return d
            elif spread_assess_pre.get("hard_veto"):
                _record_rejection("spread_hard", ctx)
                d = HybridDecision(
                    ok=False,
                    total_score=0,
                    tier="none",
                    reason_skip="spread_hard_veto",
                    context=ctx,
                    hard_veto="spread_hard",
                )
                if log_decision:
                    _log(d, signal, execution_path)
                return d
        except Exception:
            pass

    regime_id = "chop"
    regime_conf = 0.5
    regime_policy = None
    regime_stake_mult = 1.0
    regime_notes: list[str] = []
    regime_runtime: dict[str, Any] = {}
    if profile.get("evrim_regime_enabled", True):
        try:
            from elite_trader.evrim_market_regime import (
                apply_regime_to_context,
                apply_regime_to_runtime,
                classify_market_regime,
            )

            regime_id, regime_conf, regime_policy = classify_market_regime(
                ctx, side, profile
            )
            apply_regime_to_context(ctx, regime_id, regime_conf, regime_policy)
            if (
                regime_policy.veto
                and not regime_policy.allow_enter
                and regime_id not in ("news_shock", "chop", "low_volatility")
            ):
                _record_rejection(f"regime_{regime_id}", ctx)
                d = HybridDecision(
                    ok=False,
                    total_score=0,
                    tier="none",
                    reason_skip=f"regime_{regime_id}",
                    context=ctx,
                    hard_veto=f"regime_{regime_id}",
                )
                if log_decision:
                    _log(d, signal, execution_path)
                return d
        except Exception as exc:
            ctx["regime_error"] = str(exc)[:80]

    pa_notes: list[str] = []
    pa_analysis = None
    pa_stake_mult = 1.0
    pa, pa_notes, pa_analysis, pa_stake_mult = _score_price_action(
        signal, side, ctx, profile
    )

    if pa_analysis and pa_analysis.veto:
        _record_rejection("fake_breakout", {"prob": pa_analysis.fake_breakout_prob})
        from elite_trader.evrim_price_action import apply_pa_to_context

        apply_pa_to_context(ctx, pa_analysis)
        d = HybridDecision(
            ok=False,
            total_score=0,
            tier="none",
            reason_skip=f"fake_breakout (p={pa_analysis.fake_breakout_prob:.2f})",
            context=ctx,
            hard_veto="fake_breakout",
        )
        if log_decision:
            _log(d, signal, execution_path)
        return d

    if pa_analysis:
        from elite_trader.evrim_price_action import apply_pa_to_context

        apply_pa_to_context(ctx, pa_analysis)

    ctx.setdefault("symbol", symbol)
    vo_analysis = None
    vo_stake_mult = 1.0
    vo_notes: list[str] = []
    if profile.get("evrim_vo_enabled", True):
        try:
            from elite_trader.evrim_volume_orderbook import (
                analyze_volume_orderbook,
                apply_vo_adjustments,
                apply_vo_to_context,
                merge_vo_into_components,
                score_orderbook_component,
                score_volume_component,
            )

            vo_analysis = analyze_volume_orderbook(ctx, side, profile)
            apply_vo_to_context(ctx, vo_analysis)
            if vo_analysis.veto:
                _record_rejection("spread_wide", {"spread": vo_analysis.spread_pct})
                d = HybridDecision(
                    ok=False,
                    total_score=0,
                    tier="none",
                    reason_skip=f"spread_hard ({vo_analysis.spread_pct:.4f}%)",
                    context=ctx,
                    hard_veto="spread_hard",
                )
                if log_decision:
                    _log(d, signal, execution_path)
                return d
            vo_stake_mult = float(vo_analysis.stake_mult)
            vo_notes = list(vo_analysis.notes)
            vol = score_volume_component(ctx, profile, vo_analysis)
            ob = score_orderbook_component(ctx, side, profile, vo_analysis)
        except Exception as exc:
            ctx["vo_error"] = str(exc)[:80]
            vol = _score_volume(ctx, profile)
            ob = _score_orderbook(ctx, profile)
    else:
        vol = _score_volume(ctx, profile)
        ob = _score_orderbook(ctx, profile)

    radar_result = None
    radar_stake_mult = 1.0
    radar_notes: list[str] = []
    if profile.get("evrim_market_radar_enabled", True):
        try:
            from elite_trader.evrim_market_radar import (
                apply_radar_score_deltas,
                apply_radar_to_context,
                scan_market_radar,
            )

            radar_result = scan_market_radar(symbol, side, ctx, profile)
            apply_radar_to_context(ctx, radar_result)
            radar_stake_mult = float(radar_result.stake_mult)
            radar_notes = list(radar_result.notes)
            if radar_result.veto:
                extreme = str(radar_result.veto_reason or "") in (
                    "dd_halt",
                    "api_slow",
                    "spread_extreme",
                    "spread_halt",
                )
                if extreme:
                    _record_rejection(
                        radar_result.veto_reason or "radar_veto",
                        ctx.get("market_radar") or {},
                    )
                    d = HybridDecision(
                        ok=False,
                        total_score=0,
                        tier="none",
                        reason_skip=radar_result.veto_reason or "radar_veto",
                        context=ctx,
                        hard_veto=radar_result.veto_reason or "radar_veto",
                    )
                    if log_decision:
                        _log(d, signal, execution_path)
                    return d
                ctx["radar_penalty_applied"] = True
        except Exception as exc:
            ctx["radar_error"] = str(exc)[:80]

    vat = _score_volatility(ctx, profile)
    tr = _score_trend(side, ctx)
    nw = _score_news_whale(symbol, ctx, profile)
    if vo_analysis and vo_analysis.signals.get("whale_news_placeholder"):
        nw = _clamp(nw + 0.5, 0, COMPONENT_MAX["news_whale_risk"])
    ex, expected_net = _score_execution(profile)

    components = {
        "price_action": round(pa, 2),
        "volume_delta": round(vol, 2),
        "volatility_atr": round(vat, 2),
        "trend_ema": round(tr, 2),
        "orderbook_liquidity": round(ob, 2),
        "news_whale_risk": round(nw, 2),
        "execution_quality": round(ex, 2),
    }
    if radar_result:
        try:
            from elite_trader.evrim_market_radar import apply_radar_score_deltas

            components = apply_radar_score_deltas(side, components, radar_result)
        except Exception:
            pass
    mtf_notes: list[str] = []
    chop_mode = False
    mtf_stake_mult = 1.0
    prof_eval = dict(profile)
    if vo_analysis and profile.get("evrim_vo_enabled", True):
        try:
            from elite_trader.evrim_volume_orderbook import (
                apply_vo_adjustments,
                merge_vo_into_components,
            )

            vo_adj = apply_vo_adjustments(side, components, vo_analysis, profile)
            components = merge_vo_into_components(components, vo_adj)
            vo_notes.extend(vo_adj.notes)
            if vo_adj.max_tier_cap:
                tier_order = ["none", "normal", "aggressive", "max_aggressive"]
                cur_max = str(prof_eval.get("evrim_max_tier") or "max_aggressive")
                if tier_order.index(vo_adj.max_tier_cap) < tier_order.index(cur_max):
                    prof_eval["evrim_max_tier"] = vo_adj.max_tier_cap
        except Exception:
            pass
    if profile.get("evrim_mtf_enabled", True):
        try:
            from elite_trader.evrim_mtf_indicators import (
                apply_mtf_adjustments,
                compute_mtf_snapshot,
                merge_mtf_into_components,
            )

            mtf_snap = compute_mtf_snapshot(symbol, prof_eval)
            mtf_adj = apply_mtf_adjustments(side, components, mtf_snap, prof_eval)
            components = merge_mtf_into_components(components, mtf_adj)
            mtf_notes = list(mtf_adj.notes)
            chop_mode = bool(mtf_adj.chop_mode)
            mtf_stake_mult = float(mtf_adj.stake_mult)
            if mtf_adj.min_score_delta:
                min_score += int(mtf_adj.min_score_delta)
            if mtf_adj.max_tier_cap:
                prof_eval["evrim_max_tier"] = mtf_adj.max_tier_cap
            ctx["mtf"] = {
                "summary": mtf_snap.get("summary"),
                "adjustments": mtf_adj.component_deltas,
                "notes": mtf_notes,
            }
        except Exception as exc:
            ctx["mtf_error"] = str(exc)[:80]

    if profile.get("evrim_regime_enabled", True):
        try:
            from elite_trader.evrim_market_regime import (
                apply_regime_adjustments,
                apply_regime_to_context,
                apply_regime_to_runtime,
                classify_market_regime,
                merge_regime_into_components,
                regime_blocks_side,
            )

            regime_id, regime_conf, regime_policy = classify_market_regime(
                ctx, side, prof_eval
            )
            apply_regime_to_context(ctx, regime_id, regime_conf, regime_policy)
            if (
                regime_policy.veto
                and not regime_policy.allow_enter
                and regime_id not in ("news_shock", "chop", "low_volatility")
            ) or regime_id == "fake_pump_dump":
                pa_ctx = (ctx.get("pa") or {})
                if float(pa_ctx.get("fake_breakout_prob") or 0) >= float(
                    prof_eval.get("evrim_regime_fake_pump_prob") or 0.60
                ):
                    _record_rejection("regime_fake_pump_dump", ctx)
                    d = HybridDecision(
                        ok=False,
                        total_score=0,
                        tier="none",
                        reason_skip="regime_fake_pump_dump",
                        context=ctx,
                        hard_veto="regime_fake_pump_dump",
                    )
                    if log_decision:
                        _log(d, signal, execution_path)
                    return d
            if regime_blocks_side(regime_id, side, ctx):
                _record_rejection("regime_against_trend", ctx)
                d = HybridDecision(
                    ok=False,
                    total_score=0,
                    tier="none",
                    reason_skip="regime_against_trend",
                    context=ctx,
                    hard_veto="regime_against_trend",
                )
                if log_decision:
                    _log(d, signal, execution_path)
                return d
            apply_regime_adjustments(
                side, components, regime_id, regime_policy, prof_eval, ctx
            )
            components = merge_regime_into_components(components, regime_policy)
            min_score += int(regime_policy.min_score_delta)
            regime_stake_mult = float(regime_policy.stake_mult)
            regime_notes = list(regime_policy.notes)
            regime_runtime = apply_regime_to_runtime(prof_eval, regime_policy)
            ctx["regime_runtime"] = regime_runtime
        except Exception as exc:
            ctx["regime_error"] = str(exc)[:80]

    if radar_result:
        min_score += int(radar_result.min_score_delta or 0)

    try:
        from elite_trader.evrim_risk_policy import dynamic_min_score

        min_score = dynamic_min_score(
            str(regime_id or "chop"),
            profile,
        )
        if radar_result:
            side_delta = (
                radar_result.long_score_delta
                if side == "LONG"
                else radar_result.short_score_delta
            )
            if side_delta:
                components["news_whale_risk"] = _clamp(
                    components.get("news_whale_risk", 0) + side_delta * 0.35,
                    0,
                    10,
                )
        sr = ctx.get("spread_risk") or {}
        if sr.get("score_delta"):
            components["orderbook_liquidity"] = _clamp(
                components.get("orderbook_liquidity", 0) + float(sr["score_delta"]),
                0,
                10,
            )
    except Exception:
        pass

    if regime_id == "low_liquidity":
        _record_rejection("low_liquidity", ctx)
        d = HybridDecision(
            ok=False,
            total_score=0,
            tier="none",
            reason_skip="low_liquidity",
            context=ctx,
            hard_veto="low_liquidity",
        )
        if log_decision:
            _log(d, signal, execution_path)
        return d

    total = round(sum(components.values()), 2)
    tier = _tier_from_score(total, min_score)
    max_tier_allowed = str(prof_eval.get("evrim_max_tier") or "max_aggressive")
    tier_order = ["none", "normal", "aggressive", "max_aggressive"]
    if radar_result and radar_result.max_tier_cap:
        cap = str(radar_result.max_tier_cap)
        if tier_order.index(max_tier_allowed) > tier_order.index(cap):
            max_tier_allowed = cap
            prof_eval["evrim_max_tier"] = cap
    if tier_order.index(tier) > tier_order.index(max_tier_allowed):
        tier = max_tier_allowed

    ok = tier != "none"
    stake_mult = (
        TIER_STAKE_MULT.get(tier, 0.0)
        * mtf_stake_mult
        * pa_stake_mult
        * vo_stake_mult
        * regime_stake_mult
        * radar_stake_mult
        if ok
        else 0.0
    )
    sr = ctx.get("spread_risk") or {}
    if ok and sr.get("stake_mult"):
        stake_mult *= float(sr["stake_mult"])
    if ok and regime_id == "chop":
        try:
            from elite_trader.evrim_risk_policy import chop_policy

            stake_mult *= float(chop_policy(profile).get("stake_mult") or 0.35)
            ctx["evrim_chop_max_open"] = int(chop_policy(profile).get("max_open_cap") or 4)
        except Exception:
            pass

    dynamic_exit: dict[str, Any] = {}
    if ok:
        signal["evrim_regime"] = {
            "id": regime_id,
            "confidence": regime_conf,
            "policy": regime_policy.to_dict() if regime_policy else {},
            "runtime": regime_runtime,
        }
        try:
            from elite_trader.evrim_dynamic_exit import compute_dynamic_exit

            plan = compute_dynamic_exit(
                total_score=total,
                side=side,
                signal=signal,
                ctx=ctx,
                profile=prof_eval,
            )
            dynamic_exit = plan.to_dict()
            signal["evrim_dynamic_exit"] = dynamic_exit
            ctx["dynamic_exit"] = dynamic_exit
        except Exception as exc:
            ctx["dynamic_exit_error"] = str(exc)[:80]

        expected_net = 0.0
        if prof_eval.get("evrim_expectancy_enabled", True):
            try:
                from elite_trader.evrim_expectancy import (
                    apply_fee_protection_rules,
                    compute_pre_trade_expectancy,
                    gate_entry_from_expectancy,
                    load_expectancy_metrics,
                )

                exp_bd = compute_pre_trade_expectancy(
                    signal=signal,
                    ctx=ctx,
                    profile=prof_eval,
                    total_score=total,
                    dynamic_exit=dynamic_exit,
                )
                exp_ok, exp_reason, exp_meta = gate_entry_from_expectancy(
                    exp_bd, prof_eval
                )
                ctx["expectancy"] = exp_meta
                expected_net = exp_bd.expected_net_pnl
                if not exp_ok:
                    _record_rejection("negative_expectancy", exp_meta)
                    d = HybridDecision(
                        ok=False,
                        total_score=total,
                        tier="none",
                        reason_skip=exp_reason[:120],
                        context=ctx,
                        hard_veto="negative_expectancy",
                        expected_net_pnl_usd=expected_net,
                    )
                    if log_decision:
                        _log(d, signal, execution_path)
                    return d
                prot = apply_fee_protection_rules(
                    load_expectancy_metrics(), prof_eval
                )
                stake_mult *= float(prot.get("stake_mult") or 1.0)
                min_score += int(prot.get("min_score_delta") or 0)
                if prot.get("max_tier_cap"):
                    cap = str(prot["max_tier_cap"])
                    if tier_order.index(tier) > tier_order.index(cap):
                        tier = cap
                ctx["fee_protection"] = prot
            except Exception as exc:
                ctx["expectancy_error"] = str(exc)[:80]
        else:
            _, expected_net = _score_execution(prof_eval)

        reason_enter = (
            f"skor={total:.0f} tier={tier} "
            f"PA={components['price_action']:.0f} Vol={components['volume_delta']:.0f} "
            f"ATR={components['volatility_atr']:.0f} "
            f"Trend={components['trend_ema']:.0f} OB={components['orderbook_liquidity']:.0f} "
            f"Risk={components['news_whale_risk']:.0f} Exec={components['execution_quality']:.0f}"
        )
        notes_all = pa_notes + vo_notes + mtf_notes + regime_notes + radar_notes
        if notes_all:
            reason_enter += f" ({','.join(notes_all[:6])})"
        if radar_result and radar_result.opportunity_mode:
            reason_enter += " [OPP]"
        if radar_result and radar_result.news_sentiment not in ("neutral", ""):
            reason_enter += f" news={radar_result.news_sentiment}"
        if regime_id:
            reason_enter += f" [{regime_id}]"
        if chop_mode:
            reason_enter += " [chop]"
        if expected_net:
            reason_enter += f" E[net]=${expected_net:.2f}"
        reason_skip = ""
    else:
        reason_enter = ""
        reason_skip = f"total_below_{int(min_score)} (skor={total:.0f})"
        if nw <= 1:
            reason_skip += "; news_whale_low"
        if vol < 8:
            reason_skip += "; volume_low"
        _record_rejection("score_below_threshold", {"total": total})

    if ok:
        try:
            from elite_trader.evrim_risk_policy import log_execution_stage

            log_execution_stage(
                symbol,
                signal_passed=True,
                risk_passed=True,
                reason=f"hybrid_ok tier={tier} sc={total:.0f}",
            )
        except Exception:
            pass

    decision = HybridDecision(
        ok=ok,
        total_score=total,
        tier=tier,
        components=components,
        reason_enter=reason_enter,
        reason_skip=reason_skip.strip("; "),
        expected_net_pnl_usd=expected_net if ok else 0.0,
        stake_mult=stake_mult,
        context=ctx,
        chop_mode=chop_mode or regime_id == "chop",
        mtf_notes=mtf_notes,
    )
    if log_decision:
        _log(decision, signal, execution_path)
    if ok:
        signal["evrim_hybrid_score"] = total
        signal["evrim_stake_mult"] = stake_mult
        signal["evrim_min_score_used"] = min_score
    return decision


def _log(dec: HybridDecision, signal: dict[str, Any], execution_path: str) -> None:
    try:
        from elite_trader.evrim_cross_strategy_lab import record_hybrid_decision

        record_hybrid_decision(signal, dec, execution_path=execution_path)
    except Exception:
        pass
    if not dec.ok:
        return
    try:
        from elite_trader.evrim_decision_log import append_decision

        append_decision(
            {
                "symbol": signal.get("symbol"),
                "side": signal.get("type"),
                "entered": dec.ok,
                "tier": dec.tier,
                "total_score": dec.total_score,
                "components": dec.components,
                "reason_enter": dec.reason_enter,
                "reason_skip": dec.reason_skip,
                "expected_net_pnl_usd": dec.expected_net_pnl_usd,
                "execution_path": execution_path,
                "hard_veto": dec.hard_veto,
                "signal": {
                    "change": signal.get("change"),
                    "strength": signal.get("strength"),
                },
                "mtf": (dec.context or {}).get("mtf"),
                "pa": (dec.context or {}).get("pa"),
                "vo": (dec.context or {}).get("vo"),
                "regime": (dec.context or {}).get("regime_policy"),
                "market_regime": (dec.context or {}).get("market_regime"),
                "dynamic_exit": (dec.context or {}).get("dynamic_exit"),
                "expectancy": (dec.context or {}).get("expectancy"),
                "market_radar": (dec.context or {}).get("market_radar"),
                "chop_mode": dec.chop_mode,
            }
        )
    except Exception:
        pass


def decision_to_gate_tuple(dec: HybridDecision) -> tuple[bool, str, dict[str, Any]]:
    if dec.ok:
        ctx = dict(dec.context)
        ctx["hybrid_score"] = dec.total_score
        ctx["hybrid_tier"] = dec.tier
        ctx["hybrid_components"] = dec.components
        ctx["expected_net_pnl_usd"] = dec.expected_net_pnl_usd
        ctx["stake_mult"] = dec.stake_mult
        return True, dec.reason_enter or "hybrid_pass", ctx
    return False, dec.reason_skip or dec.hard_veto or "hybrid_fail", dec.context
