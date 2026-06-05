"""MEGA arka plan motoru — positionRisk kitap eşitleme (REST cache'den bağımsız).

Hafif REST döngüsü yalnızca mark/cache yeniler; ağır positionRisk→kitap sync burada.
"""
from __future__ import annotations

import os
import threading
import time
from typing import Any

_stop = threading.Event()
_wake = threading.Event()
_force = False
_thread: threading.Thread | None = None
_last_run_ts: float = 0.0
_last_duration_ms: float = 0.0
_inflight = False


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, str(default)))
    except ValueError:
        return default


def _interval_sec() -> float:
    return max(0.35, _env_float("MEGA_REST_SYNC_SEC", 1.5))


def position_sync_motor_alive() -> bool:
    return bool(_thread and _thread.is_alive())


def position_sync_health() -> dict[str, Any]:
    now = time.time()
    return {
        "alive": position_sync_motor_alive(),
        "last_run_ago_sec": round(now - _last_run_ts, 1) if _last_run_ts else None,
        "last_duration_ms": _last_duration_ms,
        "inflight": _inflight,
        "interval_sec": _interval_sec(),
    }


def wake_mega_position_sync(*, force: bool = False) -> None:
    global _force
    if force:
        _force = True
    _wake.set()


def _position_sync_loop() -> None:
    global _force, _last_run_ts, _last_duration_ms, _inflight
    while not _stop.is_set():
        force = bool(_force)
        _force = False
        _wake.clear()
        if not _inflight:
            _inflight = True
            t0 = time.perf_counter()
            try:
                from elite_trader.mega_live import run_mega_position_sync_tick

                run_mega_position_sync_tick(force=force)
                _last_run_ts = time.time()
            except Exception as exc:
                print(f"  ⚠ MEGA position-sync motor: {exc}")
            finally:
                _last_duration_ms = round((time.perf_counter() - t0) * 1000.0, 1)
                _inflight = False
        _wake.wait(timeout=_interval_sec())


def start_mega_position_sync_motor() -> None:
    global _thread
    from elite_trader.mega_live import mega_live_enabled

    if not mega_live_enabled():
        return
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(
        target=_position_sync_loop, name="mega-position-sync", daemon=True
    )
    _thread.start()
    wake_mega_position_sync(force=False)


def stop_mega_position_sync_motor() -> None:
    _stop.set()
    _wake.set()
    if _thread and _thread.is_alive():
        _thread.join(timeout=2.0)
