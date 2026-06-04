"""HUNTER — breakout / spike / liquidation avcısı."""
from __future__ import annotations

from typing import Any

from elite_trader.mode_engines.hunter_scoring import evaluate_hunter_entry


def evaluate(signal: dict[str, Any], ctx: dict[str, Any]) -> tuple[bool, str]:
    profile = ctx.get("profile") or {}
    if not profile.get("spread_policy"):
        profile = {
            **profile,
            "spread_policy": ctx.get("spread_policy") or "hunter_medium_penalty",
        }
    edge = float(ctx.get("edge") or signal.get("edge") or 0)
    formula = float(ctx.get("formula_score") or signal.get("formula_score") or 0)

    promoted = None
    if str(signal.get("strength") or "") != "Weak":
        try:
            from elite_trader.hunter_watchlist import try_promote

            promoted = try_promote(signal, ctx)
        except Exception:
            promoted = None
    if promoted:
        signal.update(promoted)
        strength = "Medium"
    else:
        strength = str(signal.get("strength") or "Medium")

    ok, reason, meta = evaluate_hunter_entry(
        signal,
        ctx,
        profile,
        edge=edge,
        formula=formula,
    )
    signal["hunter_meta"] = meta
    return ok, reason
