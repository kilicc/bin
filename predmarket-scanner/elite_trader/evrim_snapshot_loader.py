"""Phase 7 — load training snapshot as meta-bias only (no active_config write)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT_PATH = _ROOT / "data" / "evrim_training_snapshot" / "latest_training_snapshot.json"
EVRIM_STATE = _ROOT / "data" / "evrim_adaptive_state.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_latest_training_bias() -> dict[str, Any] | None:
    path = SNAPSHOT_PATH
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def apply_meta_bias_to_evrim_state(
    snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Meta-bias yazar — save_profile / active_config değiştirmez.
    """
    snap = snapshot if snapshot is not None else load_latest_training_bias()
    if not snap:
        return {"applied": False, "reason": "no_snapshot"}
    bias = snap.get("recommended_initial_evrim_bias") or {}
    meta_block = {
        "loaded_at": _now_iso(),
        "source": snap.get("source"),
        "created_at": snap.get("created_at"),
        "active_futures_mode_before_reset": snap.get("active_futures_mode_before_reset"),
        "mode_hints": bias.get("mode_hints") or {},
        "cross_mode": bias.get("cross_mode") or {},
        "warnings": snap.get("warnings") or [],
    }
    st: dict[str, Any] = {}
    if EVRIM_STATE.is_file():
        try:
            st = json.loads(EVRIM_STATE.read_text(encoding="utf-8"))
        except Exception:
            st = {}
    st["training_snapshot_bias"] = meta_block
    st["pre_reset_meta_bias"] = {
        "mode_summaries_keys": list((snap.get("mode_summaries") or {}).keys()),
        "regime_lessons_n": len(snap.get("regime_lessons") or {}),
        "symbol_lessons_n": len(snap.get("symbol_lessons") or {}),
    }
    EVRIM_STATE.parent.mkdir(parents=True, exist_ok=True)
    EVRIM_STATE.write_text(json.dumps(st, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        from elite_trader.evrim_cross_mode_learner import _load_state, _save_state  # noqa: SLF001

        cm = _load_state()
        cm["training_snapshot_bias"] = meta_block
        _save_state(cm)
    except Exception:
        pass
    return {"applied": True, "bias_keys": list(meta_block.keys())}


def bootstrap_training_bias_on_session() -> dict[str, Any]:
    """ensure_evrim_session hook — idempotent meta-bias load."""
    snap = load_latest_training_bias()
    if not snap:
        return {"applied": False, "reason": "no_snapshot"}
    if EVRIM_STATE.is_file():
        try:
            st = json.loads(EVRIM_STATE.read_text(encoding="utf-8"))
            existing = st.get("training_snapshot_bias") or {}
            if existing.get("created_at") == snap.get("created_at"):
                return {"applied": False, "reason": "already_loaded", "created_at": existing.get("created_at")}
        except Exception:
            pass
    return apply_meta_bias_to_evrim_state(snap)
