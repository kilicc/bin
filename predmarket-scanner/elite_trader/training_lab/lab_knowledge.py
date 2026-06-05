"""Bootstrap lab knowledge from existing system artifacts (no LLM)."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from elite_trader.training_lab import lab_store

_ROOT = Path(__file__).resolve().parent.parent.parent

# Max chars per ingested file (keep lab RAG light for trading bots)
_MAX_CHARS = 48_000


def _write_doc(name: str, text: str) -> Path | None:
    text = text.strip()
    if not text:
        return None
    if len(text) > _MAX_CHARS:
        text = text[: _MAX_CHARS] + "\n\n[truncated]\n"
    dest = lab_store.lab_data_dir() / "documents" / name
    if not name.endswith(".txt"):
        dest = dest.with_suffix(".txt")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text, encoding="utf-8")
    return dest


def _read_json(path: Path) -> Any:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _scenario_excerpt() -> str:
    scenario = os.getenv("BINANCE_ELITE_SCENARIO", "")
    if scenario and Path(scenario).is_file():
        p = Path(scenario)
    else:
        p = _ROOT / "scenarios" / "binance_elite_mega_9007_mainnet.env"
        if not p.is_file():
            p = _ROOT / "scenarios" / "binance_elite_mega_9007.env"
    if not p.is_file():
        return ""
    lines = []
    for line in p.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if any(s.startswith(pfx) for pfx in ("MEGA_", "ELITE_", "LAB_", "BERSERK2_", "BINANCE_")):
            lines.append(s)
    return f"# Scenario ({p.name})\n" + "\n".join(lines[:120])


def _latest_checkpoint_md() -> str:
    ck = _ROOT / "data" / "checkpoints"
    if not ck.is_dir():
        ck = _ROOT / "data" / "reports" / "checkpoints"
    if not ck.is_dir():
        return ""
    files = sorted(ck.glob("*.md"), key=lambda x: x.stat().st_mtime, reverse=True)
    if not files:
        return ""
    fp = files[0]
    body = fp.read_text(encoding="utf-8")[:_MAX_CHARS]
    return f"# Checkpoint {fp.name}\n{body}"


def bootstrap_system_knowledge(*, force: bool = False) -> dict[str, Any]:
    """
    Ingest current system state into lab documents/ (sidecar .txt for RAG).
    Idempotent: skips sys_* files unless force=True.
    """
    docs_dir = lab_store.lab_data_dir() / "documents"
    docs_dir.mkdir(parents=True, exist_ok=True)
    marker = docs_dir / ".knowledge_bootstrap_ts"
    if marker.is_file() and not force:
        return {"ok": True, "skipped": True, "reason": "already bootstrapped", "ts": marker.read_text().strip()}

    written: list[str] = []
    sources: list[tuple[str, Path | None, str]] = [
        ("sys_trader_knowledge.txt", _ROOT / "data" / "education" / "trader_knowledge.json", "json"),
        ("sys_9005_trade_lessons.txt", _ROOT / "data" / "elite_9005_trade_lessons.json", "json"),
        ("sys_9005_learning_registry.txt", _ROOT / "data" / "elite_9005_learning_registry.json", "json"),
        ("sys_9005_proposals.txt", _ROOT / "data" / "elite_9005_proposals.json", "json"),
        ("sys_9005_postmortem.txt", _ROOT / "data" / "elite_9005_loss_postmortem.json", "json"),
        ("sys_apex_formula.txt", _ROOT / "data" / "apex_master" / "learned_formula.json", "json"),
    ]

    for name, path, kind in sources:
        if path is None or not path.is_file():
            continue
        if kind == "json":
            data = _read_json(path)
            text = json.dumps(data, ensure_ascii=False, indent=2) if data is not None else ""
        else:
            text = path.read_text(encoding="utf-8")
        try:
            src = str(path.relative_to(_ROOT))
        except ValueError:
            src = str(path)
        text = f"# Source: {src}\n{text}"
        if _write_doc(name, text):
            written.append(name)

    postmortem_md = _ROOT / "data" / "elite_9005_loss_postmortem.md"
    if postmortem_md.is_file():
        if _write_doc("sys_postmortem_md.txt", postmortem_md.read_text(encoding="utf-8")[:_MAX_CHARS]):
            written.append("sys_postmortem_md.txt")

    scenario = _scenario_excerpt()
    if scenario and _write_doc("sys_scenario_9007.txt", scenario):
        written.append("sys_scenario_9007.txt")

    ck = _latest_checkpoint_md()
    if ck and _write_doc("sys_latest_checkpoint.txt", ck):
        written.append("sys_latest_checkpoint.txt")

    # Seed lessons from 9005 trade lessons if lab empty
    lessons_path = lab_store.lab_data_dir() / "lessons.jsonl"
    if not lessons_path.is_file() or lessons_path.stat().st_size == 0:
        tl = _read_json(_ROOT / "data" / "elite_9005_trade_lessons.json")
        if isinstance(tl, dict):
            for key, val in list(tl.items())[:40]:
                if isinstance(val, str) and val.strip():
                    lab_store.append_lesson({"text": f"[{key}] {val[:500]}", "source": "bootstrap", "tags": ["9005"]})
                elif isinstance(val, dict):
                    lab_store.append_lesson({"text": json.dumps({key: val}, ensure_ascii=False)[:500], "source": "bootstrap", "tags": ["9005"]})

    marker.write_text(datetime.now(timezone.utc).isoformat() + "\n", encoding="utf-8")
    return {"ok": True, "written": written, "documents_dir": str(docs_dir)}


def knowledge_context(*, max_chars: int = 6000) -> str:
    """RAG context: documents + recent lessons."""
    parts: list[str] = []
    chars = 0
    doc = lab_store.document_context(max_docs=8, max_chars=max_chars // 2)
    if doc:
        chunk = f"## Documents\n{doc}\n"
        parts.append(chunk)
        chars += len(chunk)
    lessons = lab_store.read_lessons(limit=12, tail=True)
    if lessons:
        lines = ["## Lessons"]
        for row in lessons:
            line = f"- {row.get('text', '')[:400]}"
            lines.append(line)
        chunk = "\n".join(lines) + "\n"
        if chars + len(chunk) <= max_chars:
            parts.append(chunk)
    return "\n".join(parts)[:max_chars]
