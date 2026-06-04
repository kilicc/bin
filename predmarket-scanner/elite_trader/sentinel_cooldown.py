"""Sentinel sembol cooldown — paper + live tutarlılık."""
from __future__ import annotations

import time

_last_close: dict[str, float] = {}
_reject_count = 0


def record_close(symbol: str) -> None:
    sym = str(symbol or "").upper()
    if sym:
        _last_close[sym] = time.time()


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


def cooldown_stats() -> dict[str, int]:
    return {"cooldown_rejects": _reject_count}
