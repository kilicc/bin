"""Evrim V2 — paper-only exploration when idle."""
from __future__ import annotations

import time
from typing import Any

_last_trade_ts = 0.0
_last_reject_ts = 0.0
_reject_count = 0
_exploration = False
_exploration_reason = ""


def touch_trade() -> None:
    global _last_trade_ts, _exploration, _exploration_reason
    _last_trade_ts = time.time()
    _exploration = False
    _exploration_reason = ""


def touch_reject() -> None:
    global _last_reject_ts, _reject_count
    _last_reject_ts = time.time()
    _reject_count += 1


def assess_exploration(
    profile: dict[str, Any],
    *,
    now: float | None = None,
) -> dict[str, Any]:
    global _exploration, _exploration_reason
    now = now if now is not None else time.time()
    idle_min = float(profile.get("evrim_v2_exploration_idle_min") or 20)
    last = max(_last_trade_ts, _last_reject_ts)
    idle_sec = now - last if last > 0 else 0

    if idle_sec >= idle_min * 60 and _reject_count >= 3:
        _exploration = True
        _exploration_reason = "idle_rejections"
    elif idle_sec >= (idle_min + 10) * 60:
        _exploration = True
        _exploration_reason = "idle_timeout"

    min_sc = float(profile.get("evrim_v2_min_final_score") or 55)
    paper_threshold = max(40.0, min_sc - 5.0)

    return {
        "exploration_mode": _exploration,
        "exploration_reason": _exploration_reason,
        "exploration_paper_only": True,
        "exploration_paper_threshold": paper_threshold,
        "idle_sec": round(idle_sec, 1),
    }


def reset_exploration() -> None:
    global _last_trade_ts, _last_reject_ts, _reject_count, _exploration, _exploration_reason
    _last_trade_ts = 0.0
    _last_reject_ts = 0.0
    _reject_count = 0
    _exploration = False
    _exploration_reason = ""
