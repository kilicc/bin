"""Hunter sembol cooldown + fakeout guard — paper ve live simülasyon."""
from __future__ import annotations

import time
from typing import Any

_last_close: dict[str, float] = {}
_fakeout_streak: dict[str, int] = {}
_fakeout_guard_until: dict[str, float] = {}
_reject_count = 0
_fakeout_guard_count = 0


def record_close(symbol: str, *, fake_breakout: bool = False) -> None:
    sym = str(symbol or "").upper()
    if not sym:
        return
    _last_close[sym] = time.time()
    if fake_breakout:
        _fakeout_streak[sym] = _fakeout_streak.get(sym, 0) + 1
        if _fakeout_streak[sym] >= 3:
            global _fakeout_guard_count
            _fakeout_guard_until[sym] = time.time() + 20 * 60.0
            _fakeout_guard_count += 1
    else:
        _fakeout_streak[sym] = 0


def check_fakeout_guard(symbol: str) -> tuple[bool, float]:
    sym = str(symbol or "").upper()
    until = _fakeout_guard_until.get(sym)
    if not until:
        return True, 0.0
    now = time.time()
    if now >= until:
        _fakeout_guard_until.pop(sym, None)
        _fakeout_streak[sym] = 0
        return True, 0.0
    return False, until - now


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
        "fakeout_guard_count": _fakeout_guard_count,
        "fakeout_guard_active": sum(
            1 for t in _fakeout_guard_until.values() if t > time.time()
        ),
    }


def reset_stats() -> None:
    global _reject_count, _fakeout_guard_count
    _reject_count = 0
    _fakeout_guard_count = 0
