"""Evrim V2 — meta-skor motoru (6 bileşen, read-only cross-mode)."""
from __future__ import annotations

from collections import defaultdict
from typing import Any


def _f(profile: dict[str, Any], key: str, default: float) -> float:
    v = profile.get(key)
    return float(v) if v is not None else default


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def read_cross_mode_summaries() -> dict[str, Any]:
    """Diğer modların özetlerini oku — yazma yok."""
    out: dict[str, Any] = {
        "berserk": {},
        "hunter": {},
        "chop_master": {},
        "sentinel": {},
    }
    try:
        from elite_trader.berserk_learning import get_suggestions

        out["berserk"] = get_suggestions().get("berserk_learning_suggestions") or {}
    except Exception:
        pass
    try:
        from elite_trader.hunter_learning import get_suggestions

        out["hunter"] = get_suggestions().get("hunter_learning_suggestions") or {}
    except Exception:
        pass
    try:
        from elite_trader.chop_learning import get_suggestions

        out["chop_master"] = get_suggestions().get("chop_learning_suggestions") or {}
    except Exception:
        pass
    try:
        from elite_trader.sentinel_learning import snapshot_for_ui
        from elite_trader.sentinel_benchmark import get_dashboard

        out["sentinel"] = {
            "learning": snapshot_for_ui(),
            "benchmark": get_dashboard().get("sentinel_benchmark") or {},
            "safe_market_score": get_dashboard().get("safe_market_score"),
            "avoid_market_now": get_dashboard().get("avoid_market_now"),
            "recommended_risk_mode": get_dashboard().get("recommended_risk_mode"),
        }
    except Exception:
        pass
    return out


def _mode_summary_usable(mode_id: str, block: dict[str, Any]) -> bool:
    """Skip neutral defaults when mode has filter-only silence (0 trades, many rejects)."""
    if not block:
        return False
    try:
        from elite_trader.parallel_universe_engine import get_universe_book
        from elite_trader.mode_reject_buffer import summary as reject_summary

        book = get_universe_book(mode_id)
        if len(book.get("closed") or []) > 0:
            return True
        rej_n = int(reject_summary(mode_id).get("reject_count") or 0)
        if rej_n > 5:
            return False
    except Exception:
        pass
    return bool(block)


def _regime_best_mode_score(regime: str, summaries: dict[str, Any]) -> float:
    regime = str(regime or "mixed").lower()
    scores: list[tuple[str, float]] = []
    b = summaries.get("berserk") or {}
    h = summaries.get("hunter") or {}
    c = summaries.get("chop_master") or {}
    s = summaries.get("sentinel") or {}

    if "trend" in regime or regime == "breakout":
        if _mode_summary_usable("sentinel", s):
            scores.append(("sentinel", float(s.get("learning", {}).get("sentinel_benchmark_score") or 50) * 0.2))
        if _mode_summary_usable("hunter", h):
            scores.append(("hunter", float(h.get("volume_spike_success_rate") or 0) * 100 * 0.15))
    if "breakout" in regime or "liquidation" in regime:
        if _mode_summary_usable("hunter", h):
            scores.append(("hunter", float(h.get("liquidation_continuation_rate") or 0) * 100 * 0.2))
    if "chop" in regime:
        if _mode_summary_usable("chop_master", c):
            scores.append(("chop", float(c.get("mean_reversion_success") or 0) * 100 * 0.2))
    if regime in ("high_volatility", "mixed", "low_volatility"):
        if _mode_summary_usable("berserk", b):
            scores.append(("berserk", float(b.get("win_rate") or 50) * 0.15))

    if not scores:
        return 8.0
    return _clamp(max(v for _, v in scores), 0.0, 20.0)


def _symbol_meta_score(symbol: str, closed: list[dict[str, Any]]) -> float:
    sym = str(symbol or "").upper()
    rows = [c for c in closed if str(c.get("symbol") or "").upper() == sym]
    if not rows:
        return 5.0
    pnls = [float(c.get("final_pnl") or c.get("net_pnl") or 0) for c in rows]
    wr = sum(1 for p in pnls if p > 0) / len(pnls)
    return _clamp(wr * 10.0 + min(3.0, len(rows) * 0.3), 0.0, 10.0)


def compute_evrim_meta_score(
    signal: dict[str, Any],
    ctx: dict[str, Any],
    profile: dict[str, Any],
    *,
    hybrid: dict[str, Any] | None = None,
    closed: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    summaries = read_cross_mode_summaries()
    regime = str(ctx.get("regime") or signal.get("market_regime") or "mixed").lower()
    hybrid = hybrid or signal.get("evrim_hybrid") or {}

    own_raw = float(hybrid.get("total_score") or ctx.get("total_score") or 0)
    own_signal_score = round(_clamp(own_raw * 0.40, 0.0, 40.0), 2)
    regime_best_mode_score = round(_regime_best_mode_score(regime, summaries), 2)
    symbol_meta_score = round(
        _symbol_meta_score(str(signal.get("symbol") or ""), closed or []),
        2,
    )

    sent = summaries.get("sentinel") or {}
    safe_raw = float(
        sent.get("safe_market_score")
        or sent.get("learning", {}).get("sentinel_benchmark_score")
        or hybrid.get("components", {}).get("execution_quality", 0) * 2
        or 50
    )
    sentinel_safe_market_score = round(_clamp(safe_raw * 0.10, 0.0, 10.0), 2)

    spread = float(ctx.get("spread_pct") or signal.get("spread_pct") or 0.06)
    slip = float(ctx.get("slippage_estimate") or signal.get("slippage_estimate") or 0.02)
    exec_raw = float(
        hybrid.get("components", {}).get("execution_quality", 0)
        or (10.0 if spread <= 0.06 else 5.0)
    )
    execution_quality_score = round(_clamp(exec_raw, 0.0, 10.0), 2)

    fee_gross = float(ctx.get("fee_gross_ratio") or signal.get("fee_gross_ratio") or 0.3)
    cost_raw = 10.0 - fee_gross * 8.0 - spread * 40.0 - slip * 30.0
    cost_quality_score = round(_clamp(cost_raw, 0.0, 10.0), 2)

    breakdown = {
        "own_signal_score": own_signal_score,
        "regime_best_mode_score": regime_best_mode_score,
        "symbol_meta_score": symbol_meta_score,
        "sentinel_safe_market_score": sentinel_safe_market_score,
        "execution_quality_score": execution_quality_score,
        "cost_quality_score": cost_quality_score,
    }
    final_score = round(
        own_signal_score
        + regime_best_mode_score
        + symbol_meta_score
        + sentinel_safe_market_score
        + execution_quality_score
        + cost_quality_score,
        2,
    )
    try:
        from elite_trader.evrim_cross_strategy_lab import get_learned_score_boost

        final_score = round(final_score + get_learned_score_boost(signal, ctx), 2)
    except Exception:
        pass

    min_sc = _f(profile, "evrim_v2_min_final_score", 55)
    norm_sc = _f(profile, "evrim_v2_normal_min", 65)
    agg_sc = _f(profile, "evrim_v2_aggressive_min", 78)
    hc_sc = _f(profile, "evrim_v2_high_conviction_min", 88)

    if final_score >= hc_sc:
        tier = "high_conviction"
    elif final_score >= agg_sc:
        tier = "aggressive"
    elif final_score >= norm_sc:
        tier = "normal"
    elif final_score >= min_sc:
        tier = "low_stake"
    else:
        tier = "observation"

    contributions = {
        "berserk_momentum": round(float((summaries.get("berserk") or {}).get("win_rate") or 0) * 0.1, 3),
        "hunter_breakout": round(float((summaries.get("hunter") or {}).get("liquidation_continuation_rate") or 0) * 10, 3),
        "chop_mean_reversion": round(float((summaries.get("chop_master") or {}).get("mean_reversion_success") or 0) * 10, 3),
        "sentinel_safe": round(sentinel_safe_market_score, 3),
    }

    return {
        "final_score": final_score,
        "meta_score_breakdown": breakdown,
        "meta_tier": tier,
        "regime_best_mode": regime,
        "cross_mode_summaries": summaries,
        "mode_contributions": contributions,
        "sentinel_risk_off": bool(sent.get("avoid_market_now")),
        "sentinel_recommended_risk_mode": sent.get("recommended_risk_mode") or "normal",
    }
