"""MEGA — büyük scalp motoru (paper veya ayrı hesapta canlı)."""
from __future__ import annotations

from typing import Any

from elite_trader.mode_engines.mega_scoring import evaluate_mega_entry


def evaluate(signal: dict[str, Any], ctx: dict[str, Any]) -> tuple[bool, str]:
    profile = ctx.get("profile") or {}
    if not profile.get("spread_policy"):
        profile = {
            **profile,
            "spread_policy": ctx.get("spread_policy") or "hunter_medium_penalty",
        }
    edge = float(ctx.get("edge") or signal.get("edge") or 0)
    formula = float(ctx.get("formula_score") or signal.get("formula_score") or 0)

    ok, reason, meta = evaluate_mega_entry(
        signal,
        ctx,
        profile,
        edge=edge,
        formula=formula,
    )
    signal["mega_meta"] = meta
    if meta.get("leverage"):
        signal["leverage"] = int(meta["leverage"])
    return ok, reason
