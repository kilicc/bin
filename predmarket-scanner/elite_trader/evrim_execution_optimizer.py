"""Evrim V2 — execution optimizer (market/limit/maker/partial)."""
from __future__ import annotations

from typing import Any


def choose_execution(
    signal: dict[str, Any],
    ctx: dict[str, Any],
    meta: dict[str, Any],
    profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    profile = profile or {}
    tier = str(meta.get("meta_tier") or "normal")
    regime = str(ctx.get("regime") or signal.get("market_regime") or "mixed").lower()
    spread = float(ctx.get("spread_pct") or signal.get("spread_pct") or 0.06)
    exec_score = float(meta.get("meta_score_breakdown", {}).get("execution_quality_score") or 5)

    order_type = "market"
    partial = False
    reason = "default_market"

    if regime in ("news", "shock", "high_volatility") or spread > 0.12:
        order_type = "limit"
        reason = "news_or_wide_spread_limit"
    elif exec_score >= 8 and tier in ("aggressive", "high_conviction"):
        order_type = "maker"
        reason = "high_exec_maker"
    elif exec_score >= 6 and spread <= 0.08:
        order_type = "limit"
        reason = "limit_preferred"
    elif tier == "high_conviction" and regime in ("breakout", "trending"):
        order_type = "partial_entry"
        partial = True
        reason = "partial_high_conviction"

    try:
        from elite_trader.berserk_learning import get_suggestions

        b = get_suggestions().get("berserk_learning_suggestions") or {}
        if float(b.get("fee_damage_score") or 0) > 0.6:
            order_type = "limit" if order_type == "market" else order_type
            reason = "berserk_fee_damage_limit"
    except Exception:
        pass

    try:
        from elite_trader.hunter_learning import get_suggestions

        h = get_suggestions().get("hunter_learning_suggestions") or {}
        if float(h.get("breakout_urgency") or 0) > 0.7 and tier in ("aggressive", "high_conviction"):
            order_type = "market"
            reason = "hunter_urgency_market"
    except Exception:
        pass

    return {
        "order_type": order_type,
        "partial_entry": partial,
        "execution_reason": reason,
        "prefer_limit": order_type in ("limit", "maker"),
    }
