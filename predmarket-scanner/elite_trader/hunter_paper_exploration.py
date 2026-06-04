"""Hunter paper exploration — minimum data mode only."""
from __future__ import annotations

from typing import Any

from elite_trader.mode_minimum_data import exploration_profile_overlay, touch_observation


def try_hunter_exploration(
    signal: dict[str, Any],
    ctx: dict[str, Any],
    profile: dict[str, Any],
    normal_reason: str,
) -> tuple[str, str, dict[str, Any]]:
    """
    Returns (action, reason, meta).
    action: allow | observation | reject
    """
    exp = exploration_profile_overlay("hunter")
    meta = signal.get("hunter_meta") or {}
    strength = str(signal.get("strength") or "Medium")
    breakout = float(meta.get("breakout_score") or signal.get("breakout_score") or 0)
    fake_risk = float(meta.get("fake_breakout_risk") or signal.get("fake_breakout_risk") or 0)
    exp_min = float(exp.get("breakout_score_min") or 62)
    fake_max = float(exp.get("fake_risk_max") or 70)

    if strength == "Weak":
        if breakout >= exp_min and fake_risk < fake_max:
            meta = dict(meta)
            meta["combined_stake_mult"] = float(exp.get("stake_mult") or 0.35) * 0.6
            meta["minimum_data_mode_active"] = True
            signal["hunter_meta"] = meta
            signal["learning_tag"] = exp.get("learning_tag")
            signal["minimum_data_mode_active"] = True
            signal["minimum_data_trade_or_observation"] = "exploration_trade"
            return "allow", "hunter_exploration_weak_breakout", meta
        signal.setdefault("hunter_watchlist", []).append(signal.get("symbol"))
        touch_observation("hunter")
        return "observation", "hunter_explore_weak_watchlist", {
            "minimum_data_reason": "weak_signal_watchlist",
            "learning_tag": exp.get("learning_tag"),
        }

    if breakout >= exp_min and fake_risk < fake_max:
        exp_net = float(meta.get("expected_net_pnl_usd") or signal.get("expected_net_pnl") or 0)
        if exp_net < -0.05:
            touch_observation("hunter")
            return "observation", "hunter_explore_negative_expectancy", {
                "learning_tag": exp.get("learning_tag"),
            }
        meta = dict(meta)
        meta["combined_stake_mult"] = float(exp.get("stake_mult") or 0.35)
        meta["minimum_data_mode_active"] = True
        signal["hunter_meta"] = meta
        signal["learning_tag"] = exp.get("learning_tag")
        signal["minimum_data_mode_active"] = True
        signal["minimum_data_trade_or_observation"] = "exploration_trade"
        return "allow", "hunter_exploration_breakout_test", meta

    if meta.get("spike_type") or "spike" in normal_reason:
        touch_observation("hunter")
        return "observation", "hunter_explore_spike_watch", {
            "learning_tag": exp.get("learning_tag"),
            "minimum_data_reason": "spike_confirmation_weak",
        }

    if "no_spike" in normal_reason or "no_breakout" in normal_reason or "breakout" in normal_reason:
        touch_observation("hunter")
        return "observation", f"hunter_explore_{normal_reason[:32]}", {
            "learning_tag": exp.get("learning_tag"),
        }

    return "reject", normal_reason, {}
