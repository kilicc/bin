"""Evrim V2 — config suggestion pipeline (no auto-apply by default)."""
from __future__ import annotations

import json
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
_SUGGESTIONS = _ROOT / "data" / "evrim_config_suggestions.json"
_BACKUP_DIR = _ROOT / "data" / "backups"


def _load_suggestions() -> dict[str, Any]:
    if not _SUGGESTIONS.exists():
        return {"pending": [], "history": []}
    try:
        return json.loads(_SUGGESTIONS.read_text(encoding="utf-8"))
    except Exception:
        return {"pending": [], "history": []}


def _save_suggestions(data: dict[str, Any]) -> None:
    _SUGGESTIONS.parent.mkdir(parents=True, exist_ok=True)
    _SUGGESTIONS.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _backup_profiles() -> str:
    _BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    src = _ROOT / "data" / "mode_profiles.json"
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    dst = _BACKUP_DIR / f"mode_profiles_pre_evrim_config_{ts}.json"
    if src.exists():
        shutil.copy2(src, dst)
    return str(dst)


def _is_root_change(changes: dict[str, Any]) -> bool:
    root_keys = {
        "tp_stake_pct",
        "sl_stake_pct",
        "max_open",
        "active_capital_pct",
        "min_stake_usd",
        "evrim_v2_min_final_score",
    }
    return bool(root_keys.intersection(changes.keys()))


def propose_config_change(
    changes: dict[str, Any],
    *,
    reason: str = "",
    source: str = "maybe_tune",
    backtest_passed: bool | None = None,
    risk_change: str = "",
    expected_improvement: str | float = "",
    source_modes: list[str] | None = None,
    task_type: str = "",
) -> dict[str, Any]:
    from elite_trader.mode_profiles import get_profile, save_profile

    evrim = dict(get_profile("evrim") or {})
    auto = bool(evrim.get("evrim_v2_config_auto_apply", False))

    if auto:
        backup = _backup_profiles()
        merged = {**evrim, **changes}
        save_profile("evrim", merged)
        try:
            from elite_trader.evrim_config_version import promote_candidate_on_approval

            promote_candidate_on_approval(changes)
        except Exception:
            pass
        return {
            "applied": True,
            "auto_apply": True,
            "backup": backup,
            "changes": changes,
        }

    approval_required = _is_root_change(changes)
    if approval_required and backtest_passed is not True:
        backtest_passed = False

    try:
        from elite_trader.evrim_config_version import set_candidate

        candidate_info = set_candidate(
            changes,
            source=source,
            task_type=task_type or source,
            risk_change=risk_change,
            expected_improvement=expected_improvement,
            source_modes=source_modes,
            approval_required=approval_required,
            backtest_passed=backtest_passed,
        )
    except Exception:
        candidate_info = {}

    suggestion = {
        "id": f"evrim_cfg_{int(time.time())}",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "reason": reason,
        "changes": changes,
        "approval_required": approval_required,
        "backtest_passed": backtest_passed,
        "risk_change": risk_change,
        "expected_improvement": expected_improvement,
        "source_modes": source_modes or [],
        "candidate_config_version": candidate_info.get("candidate_config_version"),
        "status": "pending",
    }

    data = _load_suggestions()
    data.setdefault("pending", []).append(suggestion)
    _save_suggestions(data)

    return {
        "applied": False,
        "auto_apply": False,
        "suggestion": suggestion,
        "approval_required": approval_required,
        "candidate_config_version": candidate_info.get("candidate_config_version"),
        "active_config_version": candidate_info.get("active_config_version"),
        "pending_approval": True,
        "learning_blocks_trading": False,
    }


def list_pending_suggestions() -> list[dict[str, Any]]:
    return list(_load_suggestions().get("pending") or [])


def apply_approved_config(suggestion_id: str) -> dict[str, Any]:
    from elite_trader.mode_profiles import get_profile, save_profile

    data = _load_suggestions()
    pending = data.get("pending") or []
    match = None
    rest = []
    for s in pending:
        if s.get("id") == suggestion_id:
            match = s
        else:
            rest.append(s)
    if not match:
        return {"ok": False, "error": "not_found"}

    if match.get("approval_required") and not match.get("backtest_passed"):
        return {"ok": False, "error": "backtest_required"}

    backup = _backup_profiles()
    changes = match.get("changes") or {}
    try:
        from elite_trader.evrim_config_version import promote_candidate_on_approval

        promoted = promote_candidate_on_approval(changes)
    except Exception:
        promoted = {}

    evrim = dict(get_profile("evrim") or {})
    evrim.update(changes)
    save_profile("evrim", evrim)

    match["status"] = "applied"
    match["applied_at"] = datetime.now(timezone.utc).isoformat()
    match["backup"] = backup
    match["active_config_version"] = promoted.get("active_config_version")
    data["pending"] = rest
    data.setdefault("history", []).append(match)
    _save_suggestions(data)
    return {"ok": True, "applied": match, "backup": backup, "promoted": promoted}


def reject_suggestion(suggestion_id: str) -> dict[str, Any]:
    data = _load_suggestions()
    pending = data.get("pending") or []
    match = None
    rest = []
    for s in pending:
        if s.get("id") == suggestion_id:
            match = s
            match["status"] = "rejected"
        else:
            rest.append(s)
    if not match:
        return {"ok": False, "error": "not_found"}
    data["pending"] = rest
    data.setdefault("history", []).append(match)
    _save_suggestions(data)
    if not rest:
        try:
            from elite_trader.evrim_config_version import discard_candidate

            discard_candidate()
        except Exception:
            pass
    return {"ok": True, "rejected": match}
