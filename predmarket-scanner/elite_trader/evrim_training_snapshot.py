"""Phase 3 — pre-reset Evrim training snapshot (5 mod summary)."""
from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT_DIR = _ROOT / "data" / "evrim_training_snapshot"
LATEST_PATH = SNAPSHOT_DIR / "latest_training_snapshot.json"

MODE_IDS = ("evrim", "berserk", "hunter", "chop_master", "sentinel")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _pnl(row: dict[str, Any]) -> float:
    return float(row.get("final_pnl") or row.get("net_pnl") or row.get("pnl_usd") or 0)


def _book_summary(mode_id: str) -> dict[str, Any]:
    from elite_trader.parallel_universe_engine import get_universe_book

    book = get_universe_book(mode_id)
    closed = list(book.get("closed") or [])
    open_pos = list(book.get("open") or [])
    wins = [c for c in closed if _pnl(c) > 0]
    losses = [c for c in closed if _pnl(c) < 0]
    gross_win = sum(_pnl(c) for c in wins)
    gross_loss = abs(sum(_pnl(c) for c in losses))
    pf = gross_win / gross_loss if gross_loss > 0 else (99.0 if gross_win > 0 else 0.0)
    return {
        "closed_trades": len(closed),
        "open_trades": len(open_pos),
        "win_rate": len(wins) / len(closed) if closed else 0.0,
        "profit_factor": round(pf, 4),
        "realized_pnl": round(sum(_pnl(c) for c in closed), 4),
        "starting_balance": book.get("starting_balance"),
    }


def _mode_learning_summary(mode_id: str) -> dict[str, Any]:
    out: dict[str, Any] = {"book": _book_summary(mode_id)}
    try:
        from elite_trader.data_lake.ingest import summary_for_ui

        lake = summary_for_ui()
        out["data_lake"] = lake.get(mode_id) or {}
    except Exception as exc:
        out["data_lake_error"] = str(exc)
    loaders = {
        "berserk": ("elite_trader.berserk_learning", "get_suggestions"),
        "hunter": ("elite_trader.hunter_learning", "get_suggestions"),
        "chop_master": ("elite_trader.chop_learning", "get_suggestions"),
        "sentinel": ("elite_trader.sentinel_learning", "snapshot_for_ui"),
    }
    if mode_id in loaders:
        mod, fn = loaders[mode_id]
        try:
            import importlib

            m = importlib.import_module(mod)
            out["learning"] = getattr(m, fn)()
        except Exception as exc:
            out["learning_error"] = str(exc)
    if mode_id == "sentinel":
        try:
            from elite_trader.sentinel_benchmark import get_dashboard

            out["benchmark"] = get_dashboard()
        except Exception as exc:
            out["benchmark_error"] = str(exc)
    if mode_id == "evrim":
        try:
            from elite_trader.evrim_config_version import config_version_snapshot
            from elite_trader.evrim_learning_runtime import learning_snapshot
            from elite_trader.evrim_metrics import build_evrim_health
            from elite_trader.mode_profiles import get_profile
            from elite_trader.parallel_universe_engine import get_universe_book

            prof = get_profile("evrim") or {}
            book = get_universe_book("evrim")
            out["config_version"] = config_version_snapshot()
            out["learning_runtime"] = learning_snapshot()
            out["metrics"] = build_evrim_health(book, prof)
        except Exception as exc:
            out["evrim_error"] = str(exc)
        try:
            from elite_trader.evrim_progress_engine import compute_progress
            from elite_trader.mode_profiles import get_profile
            from elite_trader.parallel_universe_engine import get_universe_book

            prof = get_profile("evrim") or {}
            book = get_universe_book("evrim")
            out["progress"] = compute_progress(book, prof)
        except Exception:
            pass
    return out


def _collect_lessons() -> dict[str, Any]:
    lessons: dict[str, Any] = {
        "regime_lessons": {},
        "symbol_lessons": {},
        "risk_lessons": {},
        "fee_spread_slippage_lessons": {},
    }
    try:
        from elite_trader.evrim_cross_mode_learner import read_cross_mode_summaries

        cross = read_cross_mode_summaries()
        lessons["cross_mode"] = cross
        for mid, block in (cross or {}).items():
            if not isinstance(block, dict):
                continue
            for k in ("regime", "symbol", "risk", "fee", "spread", "slippage"):
                if k in block:
                    bucket = f"{k}_lessons" if k != "regime" else "regime_lessons"
                    if bucket in lessons:
                        lessons[bucket][mid] = block.get(k)
    except Exception as exc:
        lessons["error"] = str(exc)
    try:
        path = _ROOT / "data" / "evrim_adaptive_state.json"
        if path.is_file():
            st = json.loads(path.read_text(encoding="utf-8"))
            lessons["evrim_adaptive_lessons"] = st.get("lessons") or {}
    except Exception:
        pass
    return lessons


def _recommended_bias(mode_summaries: dict[str, Any]) -> dict[str, Any]:
    """Read-only hints — does not apply config."""
    bias: dict[str, Any] = {"notes": [], "mode_hints": {}}
    for mid, summary in mode_summaries.items():
        book = summary.get("book") or {}
        wr = float(book.get("win_rate") or 0)
        pf = float(book.get("profit_factor") or 0)
        hint: dict[str, Any] = {}
        if wr >= 0.55 and pf >= 1.1:
            hint["weight"] = "favor"
        elif wr < 0.4 or pf < 0.85:
            hint["weight"] = "caution"
        else:
            hint["weight"] = "neutral"
        bias["mode_hints"][mid] = hint
    try:
        from elite_trader.evrim_meta_score import read_cross_mode_summaries

        bias["cross_mode"] = read_cross_mode_summaries()
    except Exception:
        pass
    return bias


def build_pre_reset_training_snapshot(
    *,
    backup_dir: str | Path | None = None,
    reason: str = "",
) -> dict[str, Any]:
    from elite_trader.panel_strategy import active_futures_mode

    warnings: list[str] = []
    mode_summaries = {mid: _mode_learning_summary(mid) for mid in MODE_IDS}
    lesson_blocks = _collect_lessons()
    payload: dict[str, Any] = {
        "created_at": _now_iso(),
        "source": "pre_reset_all_modes",
        "reason": (reason or "").strip() or "pre_reset_all_modes",
        "active_futures_mode_before_reset": active_futures_mode(),
        "mode_summaries": mode_summaries,
        "regime_lessons": lesson_blocks.get("regime_lessons") or {},
        "symbol_lessons": lesson_blocks.get("symbol_lessons") or {},
        "risk_lessons": lesson_blocks.get("risk_lessons") or {},
        "fee_spread_slippage_lessons": lesson_blocks.get("fee_spread_slippage_lessons") or {},
        "recommended_initial_evrim_bias": _recommended_bias(mode_summaries),
        "warnings": warnings,
    }
    if lesson_blocks.get("error"):
        warnings.append(str(lesson_blocks["error"]))
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = _stamp()
    ts_path = SNAPSHOT_DIR / f"{stamp}_training_snapshot.json"
    for path in (LATEST_PATH, ts_path):
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if backup_dir:
        bd = Path(backup_dir)
        if not bd.is_absolute():
            bd = _ROOT / bd
        bd.mkdir(parents=True, exist_ok=True)
        shutil.copy2(LATEST_PATH, bd / "latest_training_snapshot.json")
        shutil.copy2(ts_path, bd / ts_path.name)
    payload["paths"] = {
        "latest": str(LATEST_PATH.relative_to(_ROOT)),
        "timestamped": str(ts_path.relative_to(_ROOT)),
    }
    return payload


def latest_snapshot_path() -> Path:
    return LATEST_PATH
