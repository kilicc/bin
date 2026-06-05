"""GCP tek IP — tüm süreçler arası Binance REST bütçesi (-1003 önleme)."""
from __future__ import annotations

import fcntl
import json
import os
import time
from pathlib import Path

_WINDOW_SEC = 60.0


def _budget_path() -> Path:
    return Path(
        os.getenv("ELITE_BINANCE_REST_BUDGET_FILE", "/tmp/binancex_rest_budget.json")
    )


def _max_per_min() -> int:
    try:
        raw = int(os.getenv("ELITE_BINANCE_REST_MAX_PER_MIN", "4800"))
    except ValueError:
        return 4800
    return max(60, min(5500, raw))


def _acquire_timeout_sec() -> float:
    try:
        return max(0.5, float(os.getenv("ELITE_BINANCE_REST_ACQUIRE_SEC", "12")))
    except ValueError:
        return 12.0


def _read_state() -> dict:
    path = _budget_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        return {"events": []}
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw) if raw.strip() else {"events": []}
        if not isinstance(data, dict):
            return {"events": []}
        return data
    except (OSError, json.JSONDecodeError):
        return {"events": []}


def _write_state(data: dict) -> None:
    path = _budget_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / f".{path.name}.{os.getpid()}.{time.time_ns()}.tmp"
    try:
        tmp.write_text(json.dumps(data), encoding="utf-8")
        os.replace(tmp, path)
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


def _trim_events(events: list[float], *, now: float) -> list[float]:
    cutoff = now - _WINDOW_SEC
    return [t for t in events if t >= cutoff]


def usage_ratio() -> float:
    now = time.time()
    path = _budget_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a+", encoding="utf-8") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        data = _read_state()
        events = _trim_events(list(data.get("events") or []), now=now)
    return min(1.0, len(events) / float(_max_per_min()))


def near_limit(threshold: float | None = None) -> bool:
    try:
        thr = float(
            threshold
            if threshold is not None
            else os.getenv("ELITE_BINANCE_REST_NEAR_LIMIT", "0.82")
        )
    except ValueError:
        thr = 0.82
    return usage_ratio() >= thr


def acquire_rest_slot(*, weight: int = 1, timeout: float | None = None) -> bool:
    """Slot al — başarısız olursa REST çağrısı yapma (Binance -1003 görmez)."""
    weight = max(1, int(weight))
    deadline = time.time() + (timeout if timeout is not None else _acquire_timeout_sec())
    while time.time() < deadline:
        if _try_acquire(weight):
            return True
        time.sleep(min(0.08, max(0.02, deadline - time.time())))
    return False


def _try_acquire(weight: int) -> bool:
    now = time.time()
    path = _budget_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a+", encoding="utf-8") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        data = _read_state()
        events = _trim_events(list(data.get("events") or []), now=now)
        cap = _max_per_min()
        if len(events) + weight > cap:
            data["events"] = events
            _write_state(data)
            return False
        events.extend([now] * weight)
        data["events"] = events[-cap:]
        _write_state(data)
        return True
