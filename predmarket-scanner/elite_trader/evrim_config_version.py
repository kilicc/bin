"""Evrim — active vs candidate config versioning (trading uses active only)."""
from __future__ import annotations

import hashlib
import json
import time
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
_VERSIONS_PATH = _ROOT / "data" / "evrim_config_versions.json"

_TRADING_KEYS = frozenset({
    "role", "trading_style", "learning_access", "spread_policy",
    "min_edge", "min_formula_score", "market_cooldown_min",
    "tp_stake_pct", "sl_stake_pct", "tp_trigger_frac",
    "starting_balance", "min_stake_usd", "active_capital_pct",
    "max_open", "same_symbol_max_open", "entry_max_open",
    "entry_stake_mult", "entry_skip_cautious", "entry_block_weak",
    "scan_interval_sec", "position_check_sec", "trade_top_n",
    "evrim_min_total_score", "evrim_max_tier",
    "evrim_v2_min_final_score", "evrim_v2_aggressive_min",
    "evrim_v2_high_conviction_min", "evrim_v2_hourly_target_pct",
    "evrim_v2_daily_2x_mult", "evrim_v2_max_daily_drawdown_pct",
    "evrim_v2_half_risk_drawdown_pct", "evrim_v2_fee_gross_caution",
    "evrim_v2_fee_gross_recovery", "evrim_v2_spread_tp_veto_frac",
    "evrim_v2_slippage_tp_veto_frac", "evrim_v2_exploration_idle_min",
    "evrim_v2_config_auto_apply", "evrim_manual_stop_new_entries",
})


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _extract_trading_snapshot(profile: dict[str, Any]) -> dict[str, Any]:
    return {k: profile[k] for k in _TRADING_KEYS if k in profile}


def _version_id(prefix: str) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"{prefix}_{ts}_{int(time.time()) % 100000}"


def _hash_snapshot(snapshot: dict[str, Any]) -> str:
    raw = json.dumps(snapshot, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def _load() -> dict[str, Any]:
    if not _VERSIONS_PATH.exists():
        return {}
    try:
        return json.loads(_VERSIONS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(data: dict[str, Any]) -> None:
    _VERSIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = _now_iso()
    _VERSIONS_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def bootstrap_active_from_profile() -> dict[str, Any]:
    from elite_trader.mode_profiles import get_profile

    prof = dict(get_profile("evrim") or {})
    data = _load()
    if data.get("active_config_version") and data.get("active_snapshot"):
        return data

    snap = _extract_trading_snapshot(prof)
    vid = _version_id("evrim_cfg_active")
    data = {
        "active_config_version": vid,
        "active_snapshot": snap,
        "active_hash": _hash_snapshot(snap),
        "candidate_config_version": None,
        "candidate_snapshot": None,
        "candidate_status": "none",
        "pending_approval": False,
        "candidate_meta": {},
    }
    _save(data)
    return data


def get_active_config() -> dict[str, Any]:
    data = bootstrap_active_from_profile()
    snap = data.get("active_snapshot")
    if isinstance(snap, dict) and snap:
        return deepcopy(snap)
    from elite_trader.mode_profiles import get_profile

    return _extract_trading_snapshot(dict(get_profile("evrim") or {}))


def get_trading_profile(base_profile: dict[str, Any] | None = None) -> dict[str, Any]:
    """Merge active approved config over runtime profile for gate decisions."""
    from elite_trader.mode_profiles import get_profile

    base = dict(base_profile or get_profile("evrim") or {})
    active = get_active_config()
    if active:
        base.update(active)
    return base


def set_candidate(
    changes: dict[str, Any],
    *,
    source: str = "",
    task_type: str = "",
    risk_change: str = "",
    expected_improvement: str | float = "",
    source_modes: list[str] | None = None,
    approval_required: bool = False,
    backtest_passed: bool | None = None,
) -> dict[str, Any]:
    data = bootstrap_active_from_profile()
    active = dict(data.get("active_snapshot") or get_active_config())
    candidate = {**active, **changes}
    cid = _version_id("evrim_cfg_candidate")

    data["candidate_config_version"] = cid
    data["candidate_snapshot"] = candidate
    data["candidate_status"] = "backtest" if backtest_passed else "pending"
    data["pending_approval"] = True
    data["candidate_meta"] = {
        "source": source,
        "task_type": task_type,
        "risk_change": risk_change,
        "expected_improvement": expected_improvement,
        "source_modes": source_modes or [],
        "approval_required": approval_required,
        "backtest_passed": backtest_passed,
        "created_at": _now_iso(),
    }
    _save(data)

    try:
        from elite_trader.evrim_learning_runtime import set_last_candidate_status

        set_last_candidate_status(data["candidate_status"])
    except Exception:
        pass

    return {
        "candidate_config_version": cid,
        "candidate_snapshot": candidate,
        "pending_approval": True,
        "active_config_version": data.get("active_config_version"),
    }


def discard_candidate() -> dict[str, Any]:
    data = bootstrap_active_from_profile()
    data["candidate_config_version"] = None
    data["candidate_snapshot"] = None
    data["candidate_status"] = "discarded"
    data["pending_approval"] = bool(_load_suggestions_pending())
    data["candidate_meta"] = {}
    _save(data)
    try:
        from elite_trader.evrim_learning_runtime import set_last_candidate_status

        set_last_candidate_status("discarded")
    except Exception:
        pass
    return {"ok": True, "candidate_status": "discarded"}


def _load_suggestions_pending() -> list[dict[str, Any]]:
    try:
        from elite_trader.evrim_config_pipeline import list_pending_suggestions

        return list_pending_suggestions()
    except Exception:
        return []


def promote_candidate_on_approval(changes: dict[str, Any]) -> dict[str, Any]:
    data = bootstrap_active_from_profile()
    active = dict(data.get("active_snapshot") or get_active_config())
    active.update(changes)
    vid = _version_id("evrim_cfg_active")

    data["active_config_version"] = vid
    data["active_snapshot"] = active
    data["active_hash"] = _hash_snapshot(active)
    data["candidate_config_version"] = None
    data["candidate_snapshot"] = None
    data["candidate_status"] = "approved"
    data["pending_approval"] = bool(_load_suggestions_pending())
    data["candidate_meta"] = {}
    _save(data)

    try:
        from elite_trader.evrim_learning_runtime import set_last_candidate_status

        set_last_candidate_status("approved")
    except Exception:
        pass

    return {
        "ok": True,
        "active_config_version": vid,
        "active_snapshot": active,
    }


def config_version_snapshot() -> dict[str, Any]:
    data = bootstrap_active_from_profile()
    pending = _load_suggestions_pending()
    return {
        "active_config_version": data.get("active_config_version"),
        "candidate_config_version": data.get("candidate_config_version"),
        "pending_approval": bool(pending) or bool(data.get("pending_approval")),
        "candidate_status": data.get("candidate_status") or "none",
        "last_candidate_config_status": data.get("candidate_status") or "none",
        "candidate_meta": data.get("candidate_meta") or {},
        "trading_continues_during_learning": True,
        "learning_blocks_trading": False,
    }
