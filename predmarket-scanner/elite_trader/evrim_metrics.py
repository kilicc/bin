"""Evrim V2 — dashboard health metrics."""
from __future__ import annotations

from typing import Any

from elite_trader.evrim_exploration import assess_exploration
from elite_trader.evrim_meta_score import read_cross_mode_summaries
from elite_trader.evrim_progress_engine import compute_progress
from elite_trader.evrim_recovery import recovery_state
from elite_trader.evrim_config_pipeline import list_pending_suggestions


def build_evrim_health(
    book: dict[str, Any],
    profile: dict[str, Any],
    *,
    last_meta: dict[str, Any] | None = None,
    last_risk: dict[str, Any] | None = None,
) -> dict[str, Any]:
    progress = compute_progress(book, profile)
    exploration = assess_exploration(profile)
    recovery = recovery_state()
    summaries = read_cross_mode_summaries()
    pending = list_pending_suggestions()

    meta = last_meta or {}
    risk = last_risk or {}

    learning_fields: dict[str, Any] = {
        "learning_active": False,
        "learning_blocks_trading": False,
        "trading_continues_during_learning": True,
    }
    config_fields: dict[str, Any] = {}
    try:
        from elite_trader.evrim_learning_runtime import learning_snapshot

        learning_fields = learning_snapshot()
    except Exception:
        pass
    try:
        from elite_trader.evrim_config_version import config_version_snapshot

        config_fields = config_version_snapshot()
    except Exception:
        pass

    contributions = meta.get("mode_contributions") or {
        "berserk_momentum": summaries.get("berserk", {}).get("win_rate"),
        "hunter_breakout": summaries.get("hunter", {}).get("liquidation_continuation_rate"),
        "chop_mean_reversion": summaries.get("chop_master", {}).get("mean_reversion_success"),
        "sentinel_safe": summaries.get("sentinel", {}).get("safe_market_score"),
    }

    motor_open = not bool(risk.get("risk_veto")) and not bool(
        learning_fields.get("learning_blocks_trading")
    )

    return {
        "evrim_v2": True,
        "final_score": meta.get("final_score"),
        "meta_tier": meta.get("meta_tier"),
        "meta_score_breakdown": meta.get("meta_score_breakdown") or {},
        "mode_contributions": contributions,
        "progress": progress,
        "risk_level": risk.get("risk_level", "normal"),
        "risk_veto": risk.get("risk_veto", False),
        "recovery_mode": recovery.get("active", False),
        "recovery_reason": recovery.get("reason", ""),
        "exploration_mode": exploration.get("exploration_mode", False),
        "exploration_reason": exploration.get("exploration_reason", ""),
        "config_suggestions_pending": len(pending),
        "config_suggestions": pending[:5],
        "sentinel_risk_off": meta.get("sentinel_risk_off", False),
        "cross_mode_summaries": {
            k: {kk: vv for kk, vv in (v or {}).items() if kk in (
                "win_rate", "mean_reversion_success", "liquidation_continuation_rate",
                "safe_market_score", "avoid_market_now", "recommended_risk_mode",
            )}
            for k, v in summaries.items()
        },
        "learning_active": learning_fields.get("learning_active", False),
        "learning_blocks_trading": False,
        "trading_continues_during_learning": True,
        "learning_task_type": learning_fields.get("learning_task_type"),
        "last_learning_result": learning_fields.get("last_learning_result"),
        "risk_mode_during_learning": learning_fields.get("risk_mode_during_learning"),
        "active_config_version": config_fields.get("active_config_version"),
        "candidate_config_version": config_fields.get("candidate_config_version"),
        "pending_approval": config_fields.get("pending_approval") or bool(pending),
        "last_candidate_config_status": config_fields.get("last_candidate_config_status"),
        "trading_motor_open": motor_open,
    }
