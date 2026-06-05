"""CHOP_MASTER V2 — mean reversion lab."""
from __future__ import annotations

from typing import Any

from elite_trader.mode_engines.chop_scoring import evaluate_chop_entry


def evaluate(signal: dict[str, Any], ctx: dict[str, Any]) -> tuple[bool, str]:
    profile = ctx.get("profile") or {}
    if not profile.get("spread_policy"):
        profile = {
            **profile,
            "spread_policy": ctx.get("spread_policy") or "chop_tight",
        }
    edge = float(ctx.get("edge") or signal.get("edge") or 0)
    formula = float(ctx.get("formula_score") or signal.get("formula_score") or 0)
    ok, reason, meta = evaluate_chop_entry(
        signal,
        ctx,
        profile,
        edge=edge,
        formula=formula,
    )
    signal["chop_meta"] = meta
    return ok, reason
