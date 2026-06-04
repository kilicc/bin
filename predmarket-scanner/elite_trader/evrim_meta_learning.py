"""
Evrim meta-öğrenme v2 — 50 döngü; yalnızca evrim profil önerisi (diğer modlara yazmaz).
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

from elite_trader.data_lake.ingest import ingest_meta_learning, summary_for_ui
from elite_trader.mode_registry import PAPER_LAB_IDS

_ROOT = Path(__file__).resolve().parent.parent
_STATE_PATH = _ROOT / "data" / "evrim_meta_learning_state.json"
_PROPOSALS_PATH = _ROOT / "data" / "evrim_config_proposals.json"
_CYCLE_SIZE = 50

_BOUNDS = {
    "tp_stake_pct": 0.15,
    "sl_stake_pct": 0.15,
    "evrim_min_total_score": 5,
    "max_open": 2,
}


def _load_state() -> dict[str, Any]:
    if not _STATE_PATH.is_file():
        return {"decision_count": 0, "cycle": 0, "last_run": 0}
    try:
        return json.loads(_STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"decision_count": 0, "cycle": 0, "last_run": 0}


def _save_state(st: dict[str, Any]) -> None:
    _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _STATE_PATH.write_text(
        json.dumps(st, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _bounded_patch(current: dict[str, Any], key: str, delta: float) -> float | int:
    cur = float(current.get(key) or 0)
    bound = _BOUNDS.get(key, 0.1)
    if key == "max_open" or key == "entry_max_open":
        return int(max(1, min(20, cur + delta)))
    if key == "evrim_min_total_score":
        return int(max(50, min(75, cur + delta)))
    return round(max(0.0005, cur * (1 + delta)), 6)


def _lab_metrics() -> dict[str, Any]:
    summary = summary_for_ui()
    out: dict[str, Any] = {}
    for mid in PAPER_LAB_IDS:
        m = summary.get(mid) or {}
        out[mid] = {
            "profit_factor": m.get("profit_factor", 0),
            "win_rate": m.get("win_rate", 0),
            "trades": m.get("trades", 0),
            "top_rejects": m.get("top_rejects", []),
        }
    return out


def run_meta_cycle(force: bool = False) -> dict[str, Any]:
    """50 karar sonrası meta özet + evrim profil önerisi."""
    st = _load_state()
    st["decision_count"] = int(st.get("decision_count", 0)) + 1
    if not force and st["decision_count"] % _CYCLE_SIZE != 0:
        _save_state(st)
        return {"ok": True, "skipped": True, "decision_count": st["decision_count"]}

    def _cycle_body() -> dict[str, Any]:
        labs = _lab_metrics()
        best_pf = max((labs[m].get("profit_factor") or 0) for m in labs) if labs else 0
        worst_fg = 0.0

        proposals: dict[str, Any] = {"mode_id": "evrim", "ts": time.time(), "adjustments": {}}
        try:
            from elite_trader.panel_strategy import mode_catalog

            cur = dict(mode_catalog().get("evrim") or {})
        except Exception:
            cur = {}

        if best_pf > 1.2 and worst_fg < 0.6:
            proposals["adjustments"]["tp_stake_pct"] = _bounded_patch(
                cur, "tp_stake_pct", 0.03
            )
            proposals["adjustments"]["evrim_min_total_score"] = _bounded_patch(
                cur, "evrim_min_total_score", -2
            )
        elif best_pf < 0.9:
            proposals["adjustments"]["sl_stake_pct"] = _bounded_patch(cur, "sl_stake_pct", -0.05)
            proposals["adjustments"]["evrim_min_total_score"] = _bounded_patch(
                cur, "evrim_min_total_score", 2
            )

        if worst_fg > 0.6:
            proposals["note"] = "fee_gross_high_no_aggression"
            proposals["adjustments"] = {}

        summary = {
            "cycle": int(st.get("cycle", 0)) + 1,
            "lab_metrics": labs,
            "best_pf": best_pf,
            "rules_applied": list(proposals.get("adjustments") or {}),
        }
        st["cycle"] = summary["cycle"]
        st["last_run"] = time.time()
        st["last_summary"] = summary
        _save_state(st)

        _PROPOSALS_PATH.write_text(
            json.dumps(proposals, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        ingest_meta_learning(summary["cycle"], summary, proposals)

        adjustments = proposals.get("adjustments") or {}
        if adjustments:
            try:
                from elite_trader.evrim_config_pipeline import propose_config_change

                propose_config_change(
                    adjustments,
                    reason="meta_learning_cycle",
                    source="meta_learning",
                    task_type="meta_learning",
                    source_modes=list(labs.keys()),
                    risk_change=proposals.get("note") or "",
                )
            except Exception:
                pass

        return {"ok": True, "cycle": summary["cycle"], "proposals": proposals, "summary": summary}

    try:
        from elite_trader.evrim_learning_runtime import learning_task

        with learning_task("meta_learning"):
            return _cycle_body()
    except Exception:
        return _cycle_body()


def on_decision_recorded() -> None:
    """Evrim kararı — hot path dışında arka planda (motor gate segfault önleme)."""
    def _bg() -> None:
        try:
            run_meta_cycle(force=False)
        except Exception:
            pass

    threading.Thread(target=_bg, daemon=True, name="evrim-meta-bg").start()


def latest_meta_summary() -> dict[str, Any]:
    st = _load_state()
    return dict(st.get("last_summary") or {})
