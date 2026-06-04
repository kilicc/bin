"""Sentinel paper exploration — minimum data mode only."""
from __future__ import annotations

from typing import Any

from elite_trader.mode_minimum_data import exploration_profile_overlay, touch_observation


def try_sentinel_exploration(
    signal: dict[str, Any],
    ctx: dict[str, Any],
    profile: dict[str, Any],
    normal_reason: str,
) -> tuple[str, str, dict[str, Any]]:
    exp = exploration_profile_overlay("sentinel")
    meta = signal.get("sentinel_meta") or {}
    quality = float(meta.get("sentinel_quality_score") or signal.get("sentinel_quality_score") or 0)
    exec_q = float(meta.get("sentinel_execution_quality_score") or 0)
    q_min = float(exp.get("quality_min") or 68)
    e_min = float(exp.get("execution_min") or 75)
    strength = str(signal.get("strength") or "Medium")
    risk_off = bool(meta.get("sentinel_risk_off") or meta.get("avoid_market_now"))

    if risk_off:
        touch_observation("sentinel")
        try:
            from elite_trader.sentinel_benchmark import force_benchmark

            force_benchmark(signal, meta)
        except Exception:
            pass
        return "observation", "sentinel_explore_risk_off_benchmark", {
            "learning_tag": exp.get("learning_tag"),
            "minimum_data_reason": "risk_off",
        }

    if strength == "Weak":
        touch_observation("sentinel")
        return "observation", "sentinel_explore_weak_observation", {
            "learning_tag": exp.get("learning_tag"),
        }

    if quality >= q_min and exec_q >= e_min:
        spread = float(meta.get("spread_pct") or signal.get("spread_pct") or 0)
        max_sp = float(profile.get("max_spread_pct") or 0.12)
        if spread > max_sp:
            touch_observation("sentinel")
            return "observation", "sentinel_explore_spread_strict", {"learning_tag": exp.get("learning_tag")}
        meta = dict(meta)
        meta["combined_stake_mult"] = float(exp.get("stake_mult") or 0.25)
        meta["minimum_data_mode_active"] = True
        signal["sentinel_meta"] = meta
        signal["learning_tag"] = exp.get("learning_tag")
        signal["minimum_data_mode_active"] = True
        signal["minimum_data_trade_or_observation"] = "exploration_trade"
        return "allow", "sentinel_exploration_quality_test", meta

    if quality >= q_min - 4:
        touch_observation("sentinel")
        return "observation", "sentinel_explore_quality_watch", {"learning_tag": exp.get("learning_tag")}

    touch_observation("sentinel")
    return "observation", f"sentinel_explore_{normal_reason[:32]}", {"learning_tag": exp.get("learning_tag")}
