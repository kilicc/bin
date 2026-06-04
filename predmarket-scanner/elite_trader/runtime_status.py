"""Scanner heartbeat — dashboard canlı durum (env değiştirmez)."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

_lock = Lock()


def _root() -> Path:
    return Path(__file__).resolve().parent.parent


def heartbeat_path(db_path: Path | None = None) -> Path:
    base = db_path or Path(os.getenv("PAPER_DB_PATH", "data/elite_formula.db"))
    if not base.is_absolute():
        base = _root() / base
    return base.parent / f"scanner_heartbeat_{base.stem}.json"


def write_heartbeat(
    *,
    db_path: Path | None = None,
    cycle: int = 0,
    closed_last: int = 0,
    opened_last: int = 0,
    last_full_scan_at: str | None = None,
    markets_scanned: int | None = None,
    markets_total: int | None = None,
    scan_interval_sec: float | None = None,
    position_check_sec: float | None = None,
    scan_in_progress: bool | None = None,
    last_scan_duration_sec: float | None = None,
    extra: dict | None = None,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    payload: dict = {
        "ts": now,
        "pid": os.getpid(),
        "cycle": cycle,
        "closed_last": closed_last,
        "opened_last": opened_last,
        "last_full_scan_at": last_full_scan_at,
        "last_position_check_at": now,
        "markets_scanned": markets_scanned,
        "markets_total": markets_total,
        "scan_interval_sec": scan_interval_sec,
        "position_check_sec": position_check_sec,
        "dashboard_port": (os.getenv("DASHBOARD_PORT") or "").strip(),
        "scenario": (
            os.getenv("SCENARIO_LABEL") or os.getenv("PROFILE_NAME") or ""
        ).strip(),
        "db_path": str(db_path or os.getenv("PAPER_DB_PATH", "")),
    }
    if scan_in_progress is not None:
        payload["scan_in_progress"] = bool(scan_in_progress)
    if last_scan_duration_sec is not None:
        payload["last_scan_duration_sec"] = round(float(last_scan_duration_sec), 1)
    if extra:
        payload.update(extra)
    path = heartbeat_path(db_path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with _lock:
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def read_heartbeat(db_path: Path | None = None) -> dict | None:
    path = heartbeat_path(db_path)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def age_seconds(ts: str | None) -> float | None:
    dt = _parse_iso(ts)
    if dt is None:
        return None
    return (datetime.now(timezone.utc) - dt).total_seconds()
