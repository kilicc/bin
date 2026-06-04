"""Adaptif positionRisk — hedef yakınında / geçişte REST, uzakta seyrek poll."""
from __future__ import annotations

import os
import threading
import time
from typing import Any

_urgency_lock = threading.Lock()
_last_urgency = 0
_last_wake_ts = 0.0
_last_log_ts = 0.0

URGENCY_IDLE = 0
URGENCY_WARM = 1
URGENCY_HOT = 2


def adaptive_enabled() -> bool:
    return os.getenv("ELITE_POSITION_RISK_ADAPTIVE", "0").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def _f(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def idle_interval_sec() -> float:
    return max(3.0, _f("ELITE_POSITION_RISK_IDLE_SEC", 10.0))


def warm_interval_sec() -> float:
    return max(0.5, _f("ELITE_POSITION_RISK_WARM_SEC", 1.2))


def hot_interval_sec() -> float:
    return max(0.20, _f("ELITE_POSITION_RISK_HOT_SEC", 0.34))


def max_stale_sec() -> float:
    return max(idle_interval_sec(), _f("ELITE_POSITION_RISK_MAX_STALE_SEC", 15.0))


def near_tp_frac() -> float:
    return max(0.5, min(0.98, _f("ELITE_POSITION_RISK_NEAR_TP_FRAC", 0.82)))


def near_sl_frac() -> float:
    return max(0.5, min(0.98, _f("ELITE_POSITION_RISK_NEAR_SL_FRAC", 0.75)))


def hot_tp_frac() -> float:
    return max(near_tp_frac(), _f("ELITE_POSITION_RISK_HOT_TP_FRAC", 0.95))


def _mark_for_pos(
    pos: dict[str, Any],
    bulk: dict[str, float] | None,
) -> float:
    sym = str(pos.get("symbol") or "")
    coin = sym.replace("USDT", "")
    if bulk:
        for key in (coin, sym, coin.upper()):
            px = float(bulk.get(key) or 0)
            if px > 0:
                return px
    cur = float(pos.get("current_price") or 0)
    if cur > 0:
        return cur
    return 0.0


def estimate_gross_upnl(pos: dict[str, Any], mark: float) -> float | None:
    entry = float(pos.get("entry_price") or 0)
    size = float(pos.get("size") or 0)
    if mark <= 0 or entry <= 0 or size <= 0:
        unreal = pos.get("unrealized_pnl")
        if unreal is not None:
            try:
                return float(unreal)
            except (TypeError, ValueError):
                pass
        return None
    side = str(pos.get("side") or "LONG").upper()
    if side == "SHORT":
        return (entry - mark) * size
    return (mark - entry) * size


def urgency_for_position(
    pos: dict[str, Any],
    *,
    bulk: dict[str, float] | None = None,
) -> int:
    if not pos.get("on_exchange"):
        return URGENCY_IDLE
    mark = _mark_for_pos(pos, bulk)
    gross = estimate_gross_upnl(pos, mark)
    if gross is None:
        return URGENCY_IDLE

    tp = float(pos.get("tp_target_usd") or 0)
    sl = float(pos.get("sl_target_usd") or 0)
    if tp <= 0 and sl <= 0:
        return URGENCY_IDLE

    if tp > 0:
        if gross >= tp * hot_tp_frac():
            return URGENCY_HOT
        if gross >= tp * near_tp_frac():
            return URGENCY_WARM
        prev_max = float(pos.get("max_unreal_seen") or gross)
        if prev_max >= tp * near_tp_frac() and gross >= tp * (near_tp_frac() - 0.08):
            return URGENCY_HOT

    if sl > 0:
        loss = -gross if gross < 0 else 0.0
        if loss >= sl * near_sl_frac():
            return URGENCY_HOT if loss >= sl * 0.92 else URGENCY_WARM

    try:
        from elite_trader.exchange_fill_truth import fill_gross_unreal

        if tp > 0 and gross >= tp * (near_tp_frac() - 0.05):
            fill_g = fill_gross_unreal(pos)
            if fill_g is not None and float(fill_g) >= tp * near_tp_frac():
                return URGENCY_HOT
    except Exception:
        pass

    return URGENCY_IDLE


def aggregate_urgency(
    positions: list[dict[str, Any]],
    *,
    bulk: dict[str, float] | None = None,
) -> int:
    if not positions:
        return URGENCY_IDLE
    level = URGENCY_IDLE
    for pos in positions:
        if not pos.get("on_exchange"):
            continue
        u = urgency_for_position(pos, bulk=bulk)
        if u > level:
            level = u
        if level >= URGENCY_HOT:
            break
    return level


def poll_plan(
    *,
    positions: list[dict[str, Any]],
    cache_age_sec: float,
    bulk: dict[str, float] | None = None,
    has_open: bool = True,
) -> dict[str, Any]:
    """REST positionRisk poll planı — interval + force."""
    if not adaptive_enabled():
        floor = max(0.20, _f("ELITE_EXCHANGE_POSITION_REFRESH_SEC", 0.34))
        return {
            "urgency": URGENCY_WARM if has_open else URGENCY_IDLE,
            "interval_sec": floor,
            "force": bool(has_open),
            "wait_sec": floor,
            "reason": "legacy_continuous",
        }

    if not has_open:
        idle = max(8.0, idle_interval_sec())
        return {
            "urgency": URGENCY_IDLE,
            "interval_sec": idle,
            "force": False,
            "wait_sec": idle,
            "reason": "no_open",
        }

    urgency = aggregate_urgency(positions, bulk=bulk)
    if cache_age_sec >= max_stale_sec():
        urgency = max(urgency, URGENCY_WARM)

    if urgency >= URGENCY_HOT:
        iv = hot_interval_sec()
        reason = "hot_target"
        force = True
    elif urgency >= URGENCY_WARM:
        iv = warm_interval_sec()
        reason = "near_target"
        force = cache_age_sec >= warm_interval_sec() * 0.9
    else:
        iv = idle_interval_sec()
        reason = "idle_far_from_target"
        force = cache_age_sec >= max_stale_sec()

    return {
        "urgency": urgency,
        "interval_sec": iv,
        "force": force,
        "wait_sec": iv,
        "reason": reason,
    }


def note_urgency(urgency: int, *, reason: str = "") -> None:
    global _last_urgency, _last_log_ts
    with _urgency_lock:
        prev = _last_urgency
        _last_urgency = urgency
    if urgency > prev and urgency >= URGENCY_WARM:
        now = time.time()
        if now - _last_log_ts >= 8.0:
            _last_log_ts = now
            tag = {URGENCY_IDLE: "idle", URGENCY_WARM: "warm", URGENCY_HOT: "hot"}.get(
                urgency, "?"
            )
            extra = f" · {reason}" if reason else ""
            print(f"  📡 positionRisk adaptif → {tag}{extra}")


def maybe_wake_poll(
    positions: list[dict[str, Any]],
    *,
    bulk: dict[str, float] | None,
    cache_age_sec: float,
    wake_event: threading.Event | None,
) -> dict[str, Any]:
    """Fiyat tick sonrası — acil REST gerekirse uyar."""
    plan = poll_plan(
        positions=positions,
        cache_age_sec=cache_age_sec,
        bulk=bulk,
        has_open=bool(positions),
    )
    with _urgency_lock:
        prev = _last_urgency
    note_urgency(int(plan["urgency"]), reason=str(plan.get("reason") or ""))
    if wake_event is None:
        return plan
    if int(plan["urgency"]) > prev or (
        int(plan["urgency"]) >= URGENCY_HOT and cache_age_sec > hot_interval_sec()
    ):
        global _last_wake_ts
        _last_wake_ts = time.time()
        wake_event.set()
    return plan
