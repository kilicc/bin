"""Training lab persistence — data/lab_9007/."""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent.parent


def lab_data_dir() -> Path:
    iid = os.getenv("MEGA_INSTANCE_ID", os.getenv("BINANCE_ELITE_PORT", "9007")).strip()
    d = _ROOT / "data" / f"lab_{iid}"
    d.mkdir(parents=True, exist_ok=True)
    (d / "sessions").mkdir(exist_ok=True)
    (d / "documents").mkdir(exist_ok=True)
    (d / "motor_runs").mkdir(exist_ok=True)
    return d


def new_session() -> str:
    sid = str(uuid.uuid4())
    p = lab_data_dir() / "sessions" / sid
    p.mkdir(parents=True, exist_ok=True)
    meta = {"id": sid, "created_at": datetime.now(timezone.utc).isoformat()}
    (p / "meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return sid


def read_session_meta(session_id: str) -> dict[str, Any]:
    p = lab_data_dir() / "sessions" / session_id / "meta.json"
    if not p.is_file():
        return {"id": session_id}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {"id": session_id}


def update_session_meta(session_id: str, patch: dict[str, Any]) -> dict[str, Any]:
    meta = read_session_meta(session_id)
    meta.update(patch)
    p = lab_data_dir() / "sessions" / session_id / "meta.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return meta


def append_message(session_id: str, role: str, content: str, **extra: Any) -> None:
    p = lab_data_dir() / "sessions" / session_id / "messages.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "role": role,
        "content": content,
        **extra,
    }
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def read_messages(session_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
    p = lab_data_dir() / "sessions" / session_id / "messages.jsonl"
    if not p.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except Exception:
            continue
    return rows[-limit:]


def list_sessions(limit: int = 20) -> list[dict[str, Any]]:
    root = lab_data_dir() / "sessions"
    out: list[dict[str, Any]] = []
    for d in sorted(root.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
        if not d.is_dir():
            continue
        meta = read_session_meta(d.name)
        out.append(meta)
        if len(out) >= limit:
            break
    return out


def save_document(filename: str, data: bytes) -> Path:
    safe = "".join(c for c in filename if c.isalnum() or c in "._-")[:120]
    dest = lab_data_dir() / "documents" / safe
    dest.write_bytes(data)
    return dest


def list_documents(*, limit: int = 20) -> list[dict[str, Any]]:
    root = lab_data_dir() / "documents"
    out: list[dict[str, Any]] = []
    for fp in sorted(root.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
        if not fp.is_file() or fp.suffix == ".txt":
            continue
        sidecar = fp.with_suffix(".txt")
        out.append(
            {
                "name": fp.name,
                "bytes": fp.stat().st_size,
                "has_text": sidecar.is_file(),
                "mtime": fp.stat().st_mtime,
            }
        )
        if len(out) >= limit:
            break
    return out


def document_context(*, max_docs: int = 3, max_chars: int = 4000) -> str:
    """RAG-lite: last ingested .txt sidecar summaries (sys_* first)."""
    root = lab_data_dir() / "documents"
    parts: list[str] = []
    chars = 0
    for fp in sorted(
        root.glob("*.txt"),
        key=lambda x: (0 if x.name.startswith("sys_") else 1, -x.stat().st_mtime),
    ):
        if fp.name.endswith(".pdf.txt"):
            title = fp.name
        else:
            title = fp.name
        try:
            text = fp.read_text(encoding="utf-8")[:2000].strip()
        except Exception:
            continue
        if not text:
            continue
        chunk = f"--- {title} ---\n{text}\n"
        if chars + len(chunk) > max_chars:
            break
        parts.append(chunk)
        chars += len(chunk)
        if len(parts) >= max_docs:
            break
    return "\n".join(parts)


def append_lesson(row: dict[str, Any]) -> None:
    p = lab_data_dir() / "lessons.jsonl"
    row = {"ts": datetime.now(timezone.utc).isoformat(), **row}
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def read_lessons(*, limit: int = 50, tail: bool = True) -> list[dict[str, Any]]:
    p = lab_data_dir() / "lessons.jsonl"
    if not p.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except Exception:
            continue
    if tail:
        rows = rows[-limit:]
    else:
        rows = rows[:limit]
    return rows


def list_lessons(limit: int = 50) -> list[dict[str, Any]]:
    return read_lessons(limit=limit, tail=True)


def save_motor_run(name: str, payload: dict[str, Any]) -> str:
    rid = str(uuid.uuid4())[:8]
    p = lab_data_dir() / "motor_runs" / f"{name}_{rid}.json"
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return rid
