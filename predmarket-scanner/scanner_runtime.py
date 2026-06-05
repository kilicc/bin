"""
Ortak süreç koruması ve heartbeat (crypto_engine + crypto_futures_scanner).

- Unix: fcntl dosya kilidi (LOCK_EX | LOCK_NB) — ikinci örnek başlamaz.
- Windows: fcntl yoksa kilit atlanır (geliştirici uyarısı stderr).
"""
from __future__ import annotations

import contextlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Iterator

try:
    import fcntl  # type: ignore[attr-defined]
except ImportError:
    fcntl = None  # type: ignore[assignment]


@contextlib.contextmanager
def singleton_process_lock(lock_path: Path) -> Iterator[None]:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    if fcntl is None:
        print(
            "[scanner_runtime] UYARI: fcntl yok (Windows?). "
            "Tek örnek kilidi devre dışı — yalnızca bir süreç çalıştırın.",
            file=sys.stderr,
        )
        yield
        return

    fp = open(lock_path, "a+", encoding="utf-8")
    try:
        fcntl.flock(fp.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        fp.close()
        raise RuntimeError(
            f"Zaten çalışan bir örnek var (kilit: {lock_path}). "
            "Önce diğer süreci durdurun."
        ) from None
    try:
        fp.seek(0)
        fp.truncate()
        fp.write(str(os.getpid()))
        fp.flush()
        yield
    finally:
        try:
            fcntl.flock(fp.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        fp.close()


def write_heartbeat_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(body, encoding="utf-8")
    tmp.replace(path)


def read_heartbeat(path: Path) -> dict[str, Any] | None:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        pass
    return None
