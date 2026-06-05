"""Phase 5 — selective reset (paper books, session); preserve 9005 + config."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
EVRIM_STATE = _ROOT / "data" / "evrim_adaptive_state.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _reset_evrim_session_metrics() -> dict[str, Any]:
    """Session metrics sıfır; active_config_versions dokunulmaz."""
    st: dict[str, Any] = {}
    if EVRIM_STATE.is_file():
        try:
            st = json.loads(EVRIM_STATE.read_text(encoding="utf-8"))
        except Exception:
            st = {}
    preserved = {
        k: st.get(k)
        for k in (
            "cross_mode_bootstrap",
            "cross_mode_observations",
            "lessons",
            "training_snapshot_bias",
            "pre_reset_meta_bias",
        )
        if st.get(k) is not None
    }
    new_st = {
        "session_started_at": _now_iso(),
        "tune_history": [],
        **preserved,
    }
    EVRIM_STATE.parent.mkdir(parents=True, exist_ok=True)
    EVRIM_STATE.write_text(json.dumps(new_st, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"evrim_adaptive_state": "session_reset", "preserved_keys": list(preserved.keys())}


def _reset_runtime_caches() -> dict[str, Any]:
    out: dict[str, Any] = {}
    try:
        from elite_trader.evrim_exploration import reset_exploration

        reset_exploration()
        out["exploration"] = "reset"
    except Exception as exc:
        out["exploration_error"] = str(exc)
    try:
        from elite_trader.evrim_recovery import reset_recovery

        reset_recovery()
        out["recovery"] = "reset"
    except Exception as exc:
        out["recovery_error"] = str(exc)
    return out


def _reset_mode_books(*, reason: str) -> dict[str, Any]:
    from elite_trader.learning_preservation import reset_all_mode_books

    return reset_all_mode_books(reason=reason or "full_reset_ops")


def _clear_data_lake(*, keep_live: bool = True) -> dict[str, Any]:
    from elite_trader.data_lake.db import DB_PATH

    if not DB_PATH.is_file():
        return {"skipped": "no db"}
    conn = sqlite3.connect(str(DB_PATH))
    cleared: dict[str, int] = {}
    for tbl in ("mode_decisions", "paper_trades"):
        try:
            cur = conn.execute(f"DELETE FROM {tbl}")
            cleared[tbl] = cur.rowcount
        except Exception:
            pass
    if not keep_live:
        try:
            cur = conn.execute("DELETE FROM live_trades")
            cleared["live_trades"] = cur.rowcount
        except Exception:
            pass
    conn.commit()
    conn.close()
    return {"cleared": cleared, "live_trades_preserved": keep_live}


def run_selective_reset(
    *,
    reason: str,
    clear_data_lake: bool = False,
    clear_live_trades: bool = False,
    wipe_9005_history: bool = False,
) -> dict[str, Any]:
    """
    Backup + training snapshot sonrası seçici sıfırlama.
    Varsayılan: 9005 state DB korunur.
    """
    report: dict[str, Any] = {
        "started_at": _now_iso(),
        "reason": reason,
        "reset": [],
        "preserved": [
            "mode_profiles.json",
            "evrim_config_versions.json (active)",
            "latest_training_snapshot.json",
            "evrim_persistent_learning.json",
            "backup_manifest",
            "deleted_archives",
        ],
    }
    report["mode_books"] = _reset_mode_books(reason=reason)
    report["reset"].append("parallel_universe paper/open/closed")
    report["evrim_session"] = _reset_evrim_session_metrics()
    report["reset"].append("evrim_adaptive session metrics")
    report["runtime"] = _reset_runtime_caches()
    report["reset"].append("exploration/recovery caches")
    if clear_data_lake:
        report["data_lake"] = _clear_data_lake(keep_live=not clear_live_trades)
        report["reset"].append("data_lake mode_decisions + paper_trades")
    if wipe_9005_history:
        from elite_trader.data_archive import wipe_9005_with_archive

        report["wipe_9005"] = wipe_9005_with_archive(
            reason=reason, trigger="full_evrim_restart_pipeline"
        )
        report["reset"].append("9005 history (archived wipe)")
    report["finished_at"] = _now_iso()
    return report


def set_motor_evrim(*, note: str = "") -> dict[str, Any]:
    from elite_trader.order_gate import ORDER_ROUTE_PAPER, route_order
    from elite_trader.panel_strategy import active_futures_mode, is_live_binance_motor, mode_order, set_execution_mode

    prev = active_futures_mode()
    new_mode, msg = set_execution_mode("evrim", note=note or "full_reset_pipeline")
    verification: dict[str, Any] = {
        "previous_mode": prev,
        "new_mode": new_mode,
        "message": msg,
        "motor_live": {},
        "berserk_route_paper": None,
    }
    for mid in mode_order():
        verification["motor_live"][mid] = is_live_binance_motor(mid)
    try:
        from elite_trader.order_gate import build_order_intent

        gate = route_order(
            "berserk",
            build_order_intent("berserk", symbol="BTCUSDT", side="LONG"),
            active_futures_mode="evrim",
            api_healthy=True,
            live_orders_enabled=True,
        )
        verification["berserk_route_paper"] = gate.order_route == ORDER_ROUTE_PAPER
    except Exception as exc:
        verification["berserk_route_error"] = str(exc)
    return verification
