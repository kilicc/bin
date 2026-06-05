"""Plan danışman hafızası — analizlerden öğrenilen notlar ve planlar."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
_MEMORY_PATH = _ROOT / "data" / "plan_advisor_memory.json"
_MAX_LEARNINGS = 40
_MAX_PLANS = 20


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load() -> dict[str, Any]:
    if not _MEMORY_PATH.is_file():
        return {"learnings": [], "plans": [], "updated_at": None}
    try:
        return json.loads(_MEMORY_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"learnings": [], "plans": [], "updated_at": None}


def _save(data: dict[str, Any]) -> None:
    _MEMORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = _now_iso()
    learnings = data.get("learnings") or []
    if len(learnings) > _MAX_LEARNINGS:
        data["learnings"] = learnings[-_MAX_LEARNINGS:]
    plans = data.get("plans") or []
    if len(plans) > _MAX_PLANS:
        data["plans"] = plans[-_MAX_PLANS:]
    _MEMORY_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def memory_summary_for_prompt() -> str:
    data = _load()
    lines: list[str] = []
    for p in (data.get("plans") or [])[-3:]:
        steps = p.get("steps") or []
        lines.append(
            f"Plan ({p.get('mode', '?')}): " + "; ".join(steps[:4])
        )
    for ln in (data.get("learnings") or [])[-6:]:
        lines.append(f"Öğrenilen: [{ln.get('mode', '?')}] {ln.get('insight', '')[:120]}")
    return "\n".join(lines) if lines else "Henüz kayıtlı öğrenme yok."


def record_exchange(
    user_prompt: str,
    assistant_reply: str,
    *,
    focus_mode: str | None = None,
    action_items: list[dict[str, str]] | None = None,
) -> None:
    data = _load()
    learnings = list(data.get("learnings") or [])
    snippet = (assistant_reply or "")[:280].replace("\n", " ")
    learnings.append(
        {
            "at": _now_iso(),
            "mode": focus_mode or "genel",
            "topic": (user_prompt or "")[:100],
            "insight": snippet,
        }
    )
    data["learnings"] = learnings
    if action_items:
        plans = list(data.get("plans") or [])
        steps = [it.get("title") or "" for it in action_items if it.get("title")]
        if steps:
            plans.append(
                {
                    "at": _now_iso(),
                    "mode": focus_mode or "genel",
                    "steps": steps[:8],
                    "from_prompt": (user_prompt or "")[:80],
                }
            )
        data["plans"] = plans
    _save(data)


def snapshot_for_ui() -> dict[str, Any]:
    data = _load()
    return {
        "learnings_count": len(data.get("learnings") or []),
        "plans_count": len(data.get("plans") or []),
        "recent_learnings": (data.get("learnings") or [])[-5:],
        "recent_plans": (data.get("plans") or [])[-3:],
    }
