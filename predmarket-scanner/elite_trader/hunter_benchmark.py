"""Hunter V2 — reject log + missed explosive tracking."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
_REJECT_LOG = _ROOT / "data" / "hunter_reject_log.jsonl"
_missed_explosive = 0
_reject_counts: dict[str, int] = {}


def on_hunter_reject(
    signal: dict[str, Any],
    reason: str,
    meta: dict[str, Any] | None = None,
) -> None:
    global _missed_explosive
    reason = str(reason or "unknown")[:48]
    _reject_counts[reason] = _reject_counts.get(reason, 0) + 1
    score = float(
        (meta or {}).get("breakout_score")
        or signal.get("breakout_score")
        or 0
    )
    if score >= 85:
        _missed_explosive += 1
    row = {
        "ts": time.time(),
        "symbol": signal.get("symbol"),
        "change_pct": float(signal.get("change") or 0),
        "strength": signal.get("strength"),
        "breakout_score": score,
        "fake_breakout_risk": (meta or {}).get("fake_breakout_risk"),
        "spread_pct": (meta or {}).get("spread_pct") or signal.get("spread_pct"),
        "spread_risk_level": (meta or {}).get("spread_risk_level"),
        "market_regime": signal.get("market_regime"),
        "reason": reason,
        "mode_id": "hunter",
    }
    try:
        _REJECT_LOG.parent.mkdir(parents=True, exist_ok=True)
        with _REJECT_LOG.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception:
        pass


def get_dashboard_extras() -> dict[str, Any]:
    top = sorted(_reject_counts.items(), key=lambda x: -x[1])[:8]
    return {
        "missed_explosive_moves": _missed_explosive,
        "reject_top": top,
    }


def reset_session_stats() -> None:
    global _missed_explosive
    _missed_explosive = 0
    _reject_counts.clear()
