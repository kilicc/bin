"""Evrim V2 — 2x progress engine."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _pnl(row: dict[str, Any]) -> float:
    return float(row.get("final_pnl") or row.get("net_pnl") or 0)


def compute_progress(
    book: dict[str, Any],
    profile: dict[str, Any],
    *,
    session_start_balance: float | None = None,
) -> dict[str, Any]:
    closed = list(book.get("closed") or [])
    open_p = list(book.get("open") or [])
    start = float(
        session_start_balance
        or profile.get("starting_balance")
        or 5000
    )
    daily_mult = float(profile.get("evrim_v2_daily_2x_mult") or profile.get("evrim_daily_mult") or 2.0)
    hourly_target = float(profile.get("evrim_v2_hourly_target_pct") or profile.get("evrim_hourly_target_pct") or 4.0)

    realized = sum(_pnl(c) for c in closed)
    unreal = sum(float(p.get("unrealized_pnl") or 0) for p in open_p)
    equity = start + realized + unreal
    target_equity = start * daily_mult
    progress = (equity / target_equity - 1.0) * 100.0 if target_equity > 0 else 0.0
    remaining = max(0.0, target_equity - equity)

    session_start = profile.get("_session_started_at")
    hours_elapsed = 1.0
    if session_start:
        try:
            t0 = datetime.fromisoformat(str(session_start).replace("Z", "+00:00"))
            hours_elapsed = max(0.25, (datetime.now(timezone.utc) - t0).total_seconds() / 3600.0)
        except Exception:
            pass

    hourly_net = (realized / start * 100.0) / hours_elapsed if start > 0 else 0.0
    hourly_required = hourly_target
    remaining_gap = max(0.0, hourly_required - hourly_net)

    aggression = 1.0
    if progress < -5:
        aggression = 0.85
    elif progress > 15:
        aggression = 0.75
    elif progress > 5 and hourly_net >= hourly_required * 0.8:
        aggression = 1.15
    profit_lock = progress >= 25 or (realized > 0 and progress >= 15)

    return {
        "daily_start_balance": round(start, 2),
        "current_equity": round(equity, 2),
        "target_equity": round(target_equity, 2),
        "progress_to_2x_pct": round(progress, 2),
        "hourly_required_return": round(hourly_required, 3),
        "current_hourly_net_return": round(hourly_net, 3),
        "remaining_gap_to_target": round(remaining_gap, 3),
        "remaining_usd_to_target": round(remaining, 2),
        "aggression_level": round(aggression, 3),
        "profit_lock_active": profit_lock,
        "realized_pnl": round(realized, 2),
    }
