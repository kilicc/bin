"""Chop sembol cooldown — paper ve live simülasyon."""
from __future__ import annotations

import time
from typing import Any

_last_close: dict[str, float] = {}
_reject_count = 0
_trend_guard_count = 0
_range_narrow_count = 0


def record_close(symbol: str) -> None:
    sym = str(symbol or "").upper()
    if sym:
        _last_close[sym] = time.time()


def record_trend_guard_block() -> None:
    global _trend_guard_count
    _trend_guard_count += 1


def record_range_narrow_reject() -> None:
    global _range_narrow_count
    _range_narrow_count += 1


def check_cooldown(symbol: str, cooldown_min: float) -> tuple[bool, float, bool]:
    global _reject_count
    sym = str(symbol or "").upper()
    cool = max(0.0, float(cooldown_min))
    if cool <= 0 or not sym:
        return True, 0.0, False
    last = _last_close.get(sym)
    if last is None:
        return True, 0.0, False
    elapsed = time.time() - last
    need = cool * 60.0
    if elapsed >= need:
        return True, 0.0, False
    remaining = need - elapsed
    _reject_count += 1
    return False, remaining, True


def cooldown_stats() -> dict[str, Any]:
    return {
        "cooldown_rejects": _reject_count,
        "trend_guard_count": _trend_guard_count,
        "range_too_narrow_rejects": _range_narrow_count,
    }


def reset_stats() -> None:
    global _reject_count, _trend_guard_count, _range_narrow_count
    _reject_count = 0
    _trend_guard_count = 0
    _range_narrow_count = 0
