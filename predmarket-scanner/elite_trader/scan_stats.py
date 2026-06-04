"""Tarama red sayaçları — işlem hızı diagnostik."""
from __future__ import annotations

import json
import os
from collections import defaultdict
from pathlib import Path
from threading import Lock

_lock = Lock()
_counts: dict[str, int] = defaultdict(int)
_path: Path | None = None
_enabled = False


def init(db_path: Path | None = None) -> None:
    global _path, _enabled, _counts
    _enabled = os.getenv("ELITE_SCAN_STATS", "0").strip().lower() in ("1", "true", "yes")
    if not _enabled:
        _path = None
        return
    base = db_path or Path(os.getenv("PAPER_DB_PATH", "data/elite_formula.db"))
    if not base.is_absolute():
        root = Path(__file__).resolve().parent.parent
        base = root / base
    _path = base.parent / f"scan_stats_{base.stem}.json"
    _counts = defaultdict(int)
    if _path.is_file():
        try:
            data = json.loads(_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                for k, v in data.items():
                    _counts[str(k)] = int(v)
        except Exception:
            pass


def bump(reason: str, n: int = 1) -> None:
    if not _enabled:
        return
    with _lock:
        _counts[reason] += n
        if _path:
            try:
                _path.parent.mkdir(parents=True, exist_ok=True)
                _path.write_text(json.dumps(dict(_counts)), encoding="utf-8")
            except Exception:
                pass


def _stats_path() -> Path | None:
    if _path is not None:
        return _path
    base = Path(os.getenv("PAPER_DB_PATH", "data/elite_formula.db"))
    if not base.is_absolute():
        base = Path(__file__).resolve().parent.parent / base
    return base.parent / f"scan_stats_{base.stem}.json"


def snapshot() -> dict[str, int]:
    with _lock:
        if _counts:
            return dict(_counts)
    path = _stats_path()
    if path and path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return {str(k): int(v) for k, v in data.items()}
        except Exception:
            pass
    return dict(_counts)
