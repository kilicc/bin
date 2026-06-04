"""Minimum paper data guarantee — Hunter/Chop/Sentinel only."""
from __future__ import annotations

import time
from collections import deque
from typing import Any

from elite_trader.mode_registry import resolve_mode_id
from elite_trader.panel_strategy import is_live_binance_motor

_MIN_DATA_MODES = frozenset({"hunter", "chop_master", "sentinel"})
_trade_ts: dict[str, deque[float]] = {}
_observation_ts: dict[str, deque[float]] = {}


def _profile(mode_id: str) -> dict[str, Any]:
    from elite_trader.mode_profiles import get_profile

    return dict(get_profile(mode_id) or {})


def _window_sec(profile: dict[str, Any]) -> float:
    return float(profile.get("minimum_data_window_min") or 30) * 60.0


def _min_trades(profile: dict[str, Any]) -> int:
    return int(profile.get("minimum_data_min_trades") or 1)


def _enabled(profile: dict[str, Any], mode_id: str) -> bool:
    if mode_id in ("berserk", "evrim"):
        return False
    if not profile.get("minimum_data_mode_enabled", True):
        return False
    if profile.get("minimum_data_never_live") and is_live_binance_motor(mode_id):
        return False
    return mode_id in _MIN_DATA_MODES


def touch_paper_trade(mode_id: str, *, ts: float | None = None) -> None:
    mid = resolve_mode_id(mode_id)
    now = ts if ts is not None else time.time()
    q = _trade_ts.setdefault(mid, deque(maxlen=500))
    q.append(now)


def touch_observation(mode_id: str, *, ts: float | None = None) -> None:
    mid = resolve_mode_id(mode_id)
    now = ts if ts is not None else time.time()
    q = _observation_ts.setdefault(mid, deque(maxlen=500))
    q.append(now)


def _count_in_window(q: deque[float], window_sec: float, now: float) -> int:
    cutoff = now - window_sec
    return sum(1 for t in q if t >= cutoff)


def assess_minimum_data(mode_id: str, book: dict[str, Any] | None = None) -> dict[str, Any]:
    mid = resolve_mode_id(mode_id)
    prof = _profile(mid)
    now = time.time()
    window = _window_sec(prof)
    if not _enabled(prof, mid):
        return {
            "active": False,
            "mode_id": mid,
            "reason": "disabled_or_berserk",
            "window_trade_count": 0,
            "minimum_data_only_paper": True,
            "minimum_data_never_live": True,
        }
    closed = list((book or {}).get("closed") or [])
    open_p = list((book or {}).get("open") or [])
    recent_closed = 0
    for c in closed[-50:]:
        ts = float(c.get("entry_time") or c.get("opened_at_ts") or 0)
        if ts >= now - window:
            recent_closed += 1
    mem_trades = _count_in_window(_trade_ts.get(mid, deque()), window, now)
    window_trade_count = max(recent_closed, mem_trades, len(open_p))
    active = window_trade_count < _min_trades(prof)
    reason = "zero_trades_in_window" if active else "sufficient_data"
    return {
        "active": active,
        "mode_id": mid,
        "reason": reason,
        "window_trade_count": window_trade_count,
        "window_min": prof.get("minimum_data_window_min") or 30,
        "minimum_data_min_trades": _min_trades(prof),
        "minimum_data_only_paper": bool(prof.get("minimum_data_only_paper", True)),
        "minimum_data_never_live": bool(prof.get("minimum_data_never_live", True)),
        "minimum_data_mode_active": active,
    }


def exploration_profile_overlay(mode_id: str) -> dict[str, Any]:
    """Paper-only explore params from mode profile."""
    prof = _profile(mode_id)
    mid = resolve_mode_id(mode_id)
    if mid == "hunter":
        return {
            "breakout_score_min": float(prof.get("hunter_explore_breakout_score_min") or 62),
            "fake_risk_max": float(prof.get("hunter_explore_fake_risk_max") or 70),
            "stake_mult": float(prof.get("hunter_explore_stake_mult") or 0.35),
            "max_open": int(prof.get("hunter_explore_max_open") or 2),
            "cooldown_min": float(prof.get("hunter_explore_cooldown_min") or 2.0),
            "learning_tag": prof.get("hunter_explore_learning_tag") or "hunter_exploration_breakout_test",
        }
    if mid == "chop_master":
        return {
            "chop_score_min": float(prof.get("chop_explore_chop_score_min") or 62),
            "observation_min": float(prof.get("chop_explore_observation_min") or 55),
            "range_cost_mult": float(prof.get("chop_explore_range_cost_mult") or 2.5),
            "stake_mult": float(prof.get("chop_explore_stake_mult") or 0.30),
            "max_open": int(prof.get("chop_explore_max_open") or 2),
            "cooldown_min": float(prof.get("chop_explore_cooldown_min") or 2.5),
            "learning_tag": prof.get("chop_explore_learning_tag") or "chop_exploration_mean_reversion_test",
        }
    if mid == "sentinel":
        return {
            "quality_min": float(prof.get("sentinel_explore_quality_min") or 68),
            "execution_min": float(prof.get("sentinel_explore_execution_min") or 75),
            "stake_mult": float(prof.get("sentinel_explore_stake_mult") or 0.25),
            "max_open": int(prof.get("sentinel_explore_max_open") or 1),
            "cooldown_min": float(prof.get("sentinel_explore_cooldown_min") or 5.0),
            "learning_tag": prof.get("sentinel_explore_learning_tag") or "sentinel_exploration_quality_test",
        }
    return {}


def all_status(books: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    books = books or {}
    out: dict[str, Any] = {}
    for mid in _MIN_DATA_MODES:
        out[mid] = assess_minimum_data(mid, books.get(mid))
    return out
