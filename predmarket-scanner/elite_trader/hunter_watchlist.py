"""Hunter Weak sinyal izleme — breakout adayına yükseltme."""
from __future__ import annotations

import time
from typing import Any

_WATCH: dict[str, dict[str, Any]] = {}
_TTL_SEC = 30.0


def add_weak_candidate(signal: dict[str, Any], meta: dict[str, Any]) -> None:
    sym = str(signal.get("symbol") or "").upper()
    if not sym:
        return
    _WATCH[sym] = {
        "signal": dict(signal),
        "meta": dict(meta),
        "ts": time.time(),
        "side": str(signal.get("type") or "LONG"),
        "base_change": float(signal.get("change") or 0),
    }


def _purge() -> None:
    now = time.time()
    dead = [k for k, v in _WATCH.items() if now - float(v.get("ts") or 0) > _TTL_SEC]
    for k in dead:
        _WATCH.pop(k, None)


def try_promote(signal: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any] | None:
    """Volume/orderbook/continuation ile Weak → Medium aday."""
    _purge()
    sym = str(signal.get("symbol") or "").upper()
    row = _WATCH.get(sym)
    if not row:
        return None
    age = time.time() - float(row.get("ts") or 0)
    if age < 3.0 or age > _TTL_SEC:
        return None
    side = str(signal.get("type") or row.get("side") or "LONG")
    ch = float(signal.get("change") or 0)
    base = float(row.get("base_change") or 0)
    vr = float(ctx.get("vol_ratio") or signal.get("vol_ratio") or 1.0)
    ob = float(ctx.get("orderbook_pressure") or signal.get("orderbook_pressure") or 0)
    continuation = abs(ch) >= abs(base) * 1.08 and (ch * base > 0)
    vol_accel = vr >= 1.20
    ob_ok = abs(ob) >= 0.15
    if not (continuation and (vol_accel or ob_ok)):
        return None
    promoted = dict(row["signal"])
    promoted["strength"] = "Medium"
    promoted["change"] = ch
    promoted["hunter_promoted_from_weak"] = True
    promoted["hunter_watch_age_sec"] = round(age, 1)
    _WATCH.pop(sym, None)
    return promoted


def watchlist_size() -> int:
    _purge()
    return len(_WATCH)
