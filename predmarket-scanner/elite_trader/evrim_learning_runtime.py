"""Evrim — learning runtime (learning never blocks trading by default)."""
from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

_ROOT = Path(__file__).resolve().parent.parent
_RUNTIME_PATH = _ROOT / "data" / "evrim_learning_runtime.json"

_risk_mode_during_learning = "normal"
_last_candidate_status: str | None = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_state() -> dict[str, Any]:
    return {
        "learning_active": False,
        "learning_blocks_trading": False,
        "trading_continues_during_learning": True,
        "learning_task_type": None,
        "last_learning_result": None,
        "last_candidate_config_status": None,
        "risk_mode_during_learning": "normal",
        "updated_at": _now_iso(),
    }


def _load() -> dict[str, Any]:
    if not _RUNTIME_PATH.exists():
        return _default_state()
    try:
        st = json.loads(_RUNTIME_PATH.read_text(encoding="utf-8"))
        st.setdefault("learning_blocks_trading", False)
        st.setdefault("trading_continues_during_learning", True)
        return st
    except Exception:
        return _default_state()


def _save(st: dict[str, Any]) -> None:
    st["learning_blocks_trading"] = False
    st["trading_continues_during_learning"] = True
    st["updated_at"] = _now_iso()
    _RUNTIME_PATH.parent.mkdir(parents=True, exist_ok=True)
    _RUNTIME_PATH.write_text(json.dumps(st, indent=2, ensure_ascii=False), encoding="utf-8")


def set_risk_mode_during_learning(mode: str) -> None:
    global _risk_mode_during_learning
    _risk_mode_during_learning = str(mode or "normal")
    st = _load()
    st["risk_mode_during_learning"] = _risk_mode_during_learning
    _save(st)


def set_last_candidate_status(status: str) -> None:
    global _last_candidate_status
    _last_candidate_status = status
    st = _load()
    st["last_candidate_config_status"] = status
    _save(st)


def begin_learning_task(task_type: str) -> dict[str, Any]:
    st = _load()
    st["learning_active"] = True
    st["learning_task_type"] = task_type
    st["learning_blocks_trading"] = False
    st["trading_continues_during_learning"] = True
    _save(st)
    return learning_snapshot()


def finish_learning_task(result: dict[str, Any] | str | None = None) -> dict[str, Any]:
    st = _load()
    st["learning_active"] = False
    st["learning_task_type"] = None
    st["learning_blocks_trading"] = False
    st["trading_continues_during_learning"] = True
    if result is not None:
        st["last_learning_result"] = result if isinstance(result, dict) else {"summary": str(result)}
    _save(st)
    return learning_snapshot()


@contextmanager
def learning_task(task_type: str) -> Iterator[dict[str, Any]]:
    begin_learning_task(task_type)
    try:
        yield learning_snapshot()
    finally:
        finish_learning_task()


def learning_snapshot() -> dict[str, Any]:
    st = _load()
    st["learning_blocks_trading"] = False
    st["trading_continues_during_learning"] = True
    st["risk_mode_during_learning"] = _risk_mode_during_learning or st.get("risk_mode_during_learning", "normal")
    if _last_candidate_status:
        st["last_candidate_config_status"] = _last_candidate_status
    return st


def manual_stop_new_entries(profile: dict[str, Any] | None = None) -> bool:
    if profile is None:
        try:
            from elite_trader.mode_profiles import get_profile

            profile = get_profile("evrim") or {}
        except Exception:
            profile = {}
    return bool(profile.get("evrim_manual_stop_new_entries", False))


def learning_blocks_trading() -> bool:
    return False
