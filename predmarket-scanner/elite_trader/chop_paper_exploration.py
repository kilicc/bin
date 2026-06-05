"""Chop paper exploration — minimum data mode only."""
from __future__ import annotations

from typing import Any

from elite_trader.mode_minimum_data import exploration_profile_overlay, touch_observation


def try_chop_exploration(
    signal: dict[str, Any],
    ctx: dict[str, Any],
    profile: dict[str, Any],
    normal_reason: str,
) -> tuple[str, str, dict[str, Any]]:
    exp = exploration_profile_overlay("chop_master")
    meta = signal.get("chop_meta") or {}
    chop_score = float(meta.get("chop_score") or 0)
    obs_min = float(exp.get("observation_min") or 55)
    trade_min = float(exp.get("chop_score_min") or 62)
    trend_guard = bool(meta.get("trend_guard_active") or signal.get("trend_guard_active"))
    hunter_bo = float(ctx.get("hunter_breakout_score") or signal.get("breakout_score") or 0)
    hunter_veto = float(profile.get("chop_hunter_breakout_veto") or 70)

    if hunter_bo >= hunter_veto:
        touch_observation("chop_master")
        return "observation", "chop_not_safe", {
            "learning_tag": exp.get("learning_tag"),
            "minimum_data_reason": "hunter_breakout_veto",
        }

    if trend_guard:
        touch_observation("chop_master")
        return "observation", "chop_explore_trend_guard", {
            "learning_tag": exp.get("learning_tag"),
            "minimum_data_reason": "trend_guard_active",
        }

    if chop_score >= obs_min and chop_score < trade_min:
        touch_observation("chop_master")
        return "observation", "chop_explore_observation", {
            "learning_tag": exp.get("learning_tag"),
            "chop_score": chop_score,
        }

    if chop_score >= trade_min:
        range_w = float(meta.get("range_width_pct") or ctx.get("range_width_pct") or 0)
        spread = float(signal.get("spread_pct") or ctx.get("spread_pct") or 0)
        cost = max(spread * 2, 0.01)
        if range_w >= cost * float(exp.get("range_cost_mult") or 2.5):
            exp_net = float(meta.get("expected_net_pnl_usd") or 0)
            if exp_net < -0.05:
                touch_observation("chop_master")
                return "observation", "chop_explore_negative_expectancy", {"learning_tag": exp.get("learning_tag")}
            meta = dict(meta)
            meta["combined_stake_mult"] = float(exp.get("stake_mult") or 0.30)
            meta["minimum_data_mode_active"] = True
            signal["chop_meta"] = meta
            signal["learning_tag"] = exp.get("learning_tag")
            signal["minimum_data_mode_active"] = True
            signal["minimum_data_trade_or_observation"] = "exploration_trade"
            return "allow", "chop_exploration_mean_reversion_test", meta

    touch_observation("chop_master")
    return "observation", f"chop_explore_{normal_reason[:32]}", {"learning_tag": exp.get("learning_tag")}
