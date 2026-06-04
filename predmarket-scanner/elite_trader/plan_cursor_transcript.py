"""Cursor IDE oturum transcript'i — plan danışmanına bağlam."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

# Bu sohbet (panel ↔ Cursor aynı workspace)
_DEFAULT_TRANSCRIPT = (
    Path.home()
    / ".cursor/projects/Users-macbook-Desktop-binancex/agent-transcripts"
    / "e5de62e6-5748-4179-8d05-a23810625466"
    / "e5de62e6-5748-4179-8d05-a23810625466.jsonl"
)

_TRANSCRIPTS_ROOT = (
    Path.home() / ".cursor/projects/Users-macbook-Desktop-binancex/agent-transcripts"
)


def resolve_transcript_path() -> Path | None:
    """Bağlı Cursor oturum dosyası."""
    env = (os.getenv("ELITE_PLAN_CURSOR_TRANSCRIPT") or "").strip()
    if env:
        p = Path(env).expanduser()
        if p.is_file():
            return p
    if _DEFAULT_TRANSCRIPT.is_file():
        return _DEFAULT_TRANSCRIPT
    if not _TRANSCRIPTS_ROOT.is_dir():
        return None
    candidates = sorted(
        _TRANSCRIPTS_ROOT.glob("*/*.jsonl"),
        key=lambda x: x.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


def _extract_user_text(raw: str) -> str:
    m = re.search(r"<user_query>\s*(.*?)\s*</user_query>", raw, re.DOTALL)
    if m:
        return m.group(1).strip()
    return raw.strip()


def load_transcript_turns(
    path: Path | None = None,
    *,
    max_turns: int = 14,
) -> list[dict[str, str]]:
    """Son kullanıcı/asistan mesajları (panel geçmişi ile birleştirmek için)."""
    p = path or resolve_transcript_path()
    if not p or not p.is_file():
        return []
    turns: list[dict[str, str]] = []
    try:
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        role = row.get("role")
        if role not in ("user", "assistant"):
            continue
        parts: list[str] = []
        for block in (row.get("message") or {}).get("content") or []:
            if not isinstance(block, dict) or block.get("type") != "text":
                continue
            t = (block.get("text") or "").strip()
            if not t or t.startswith("[REDACTED]"):
                continue
            if role == "user":
                t = _extract_user_text(t)
            if t:
                parts.append(t[:3500])
        if parts:
            turns.append(
                {
                    "role": "user" if role == "user" else "assistant",
                    "content": "\n".join(parts),
                }
            )
    return turns[-max_turns:]


def transcript_status() -> dict[str, Any]:
    p = resolve_transcript_path()
    turns = load_transcript_turns(p, max_turns=1) if p else []
    return {
        "bound": bool(p),
        "path": str(p) if p else None,
        "turns_loaded": len(load_transcript_turns(p)) if p else 0,
        "last_role": turns[-1]["role"] if turns else None,
    }
