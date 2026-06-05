"""Training lab API helpers — motor sandbox, chat, documents."""
from __future__ import annotations

import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from typing import Any

from elite_trader.training_lab import lab_store
from elite_trader.training_lab.lab_knowledge import bootstrap_system_knowledge, knowledge_context
from elite_trader.training_lab.llm_client import chat, vision_chat


def _executor_workers() -> int:
    try:
        return max(1, min(4, int(os.getenv("LAB_EXECUTOR_WORKERS", "1"))))
    except ValueError:
        return 1


_executor = ThreadPoolExecutor(max_workers=_executor_workers(), thread_name_prefix="lab")
_inflight = 0
_last_latency_ms: float | None = None
_queue_depth = 0


def executor_metrics() -> dict[str, Any]:
    return {
        "inflight": _inflight,
        "queue_depth": _queue_depth,
        "last_latency_ms": _last_latency_ms,
        "max_workers": _executor_workers(),
    }


def _chat_history_turns() -> int:
    try:
        return max(0, min(24, int(os.getenv("LAB_CHAT_HISTORY_TURNS", "8"))))
    except ValueError:
        return 8


def _parse_lesson_tag(text: str) -> str | None:
    m = re.search(r"<lesson>(.*?)</lesson>", text, re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return None


def ingest_text(text: str, *, name: str = "paste.txt") -> dict[str, Any]:
    data = text.encode("utf-8")
    path = lab_store.save_document(name, data)
    sidecar = path.with_suffix(".txt") if path.suffix else path.parent / (path.name + ".txt")
    sidecar.write_text(text[:200_000], encoding="utf-8")
    return {"ok": True, "path": str(path.name), "bytes": len(data)}


def ingest_pdf(data: bytes, *, name: str = "doc.pdf") -> dict[str, Any]:
    text = ""
    try:
        from pypdf import PdfReader
        import io

        reader = PdfReader(io.BytesIO(data))
        parts = []
        for page in reader.pages[:40]:
            parts.append(page.extract_text() or "")
        text = "\n".join(parts).strip()
    except Exception as exc:
        return {"ok": False, "error": f"pdf: {exc}"}
    path = lab_store.save_document(name, data)
    meta_path = path.with_suffix(".txt")
    meta_path.write_text(text[:200_000], encoding="utf-8")
    return {"ok": True, "path": path.name, "text_chars": len(text)}


def ingest_image(data: bytes, *, name: str = "chart.png", kind: str = "image/png", prompt: str = "") -> dict[str, Any]:
    path = lab_store.save_document(name, data)
    import base64

    b64 = base64.b64encode(data).decode()
    analysis = ""
    try:
        resp = vision_chat(b64, prompt or "Describe this trading chart briefly.", mime=kind)
        if resp.get("ok"):
            analysis = resp.get("text", "")
            sidecar = path.with_suffix(".txt")
            sidecar.write_text(analysis[:200_000], encoding="utf-8")
    except Exception as exc:
        return {"ok": True, "path": path.name, "vision_error": str(exc), "bytes": len(data)}
    return {"ok": True, "path": path.name, "bytes": len(data), "analysis": analysis[:2000]}


def run_motor_sandbox(motor: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = dict(payload or {})
    out: dict[str, Any] = {"motor": motor}
    if motor == "scan_summary":
        from elite_trader.mega_live import scan_summary

        out["result"] = scan_summary()
    elif motor == "regime":
        try:
            from elite_trader.mega_market_regime import regime_snapshot

            out["result"] = regime_snapshot()
        except Exception as exc:
            out["error"] = str(exc)
    elif motor == "snapshot_light":
        from elite_trader.mega_live import snapshot

        out["result"] = snapshot(light=True)
    else:
        out["error"] = f"unknown motor: {motor}"
    rid = lab_store.save_motor_run(motor, out)
    out["run_id"] = rid
    return out


def lab_chat(session_id: str, message: str, *, context: dict[str, Any] | None = None) -> dict[str, Any]:
    global _inflight, _last_latency_ms, _queue_depth
    if not session_id:
        session_id = lab_store.new_session()
    lab_store.append_message(session_id, "user", message, context=context or {})
    try:
        rag_max = max(2000, min(12_000, int(os.getenv("LAB_RAG_MAX_CHARS", "6000"))))
    except ValueError:
        rag_max = 6000
    doc_ctx = knowledge_context(max_chars=rag_max)
    sys = (
        "You are a trading lab tutor for the MEGA desk. "
        "Answer concisely about scan, exits, stake, leverage, BERSERK2/9005 lessons. "
        "Use ingested system knowledge when relevant. "
        "Optional lesson tag: wrap key takeaway in <lesson>...</lesson>. "
        f"Context: {json.dumps(context or {}, ensure_ascii=False)[:2000]}"
    )
    if doc_ctx:
        sys += f"\n\nSystem knowledge:\n{doc_ctx[:rag_max]}"
    messages: list[dict[str, str]] = [{"role": "system", "content": sys}]
    turns = _chat_history_turns()
    if turns > 0:
        hist = lab_store.read_messages(session_id, limit=turns * 2)
        for row in hist[:-1]:
            role = row.get("role", "user")
            if role in ("user", "assistant"):
                messages.append({"role": role, "content": str(row.get("content", ""))[:4000]})
    messages.append({"role": "user", "content": message})

    def _call():
        global _last_latency_ms
        t0 = time.perf_counter()
        try:
            return chat(messages)
        finally:
            _last_latency_ms = round((time.perf_counter() - t0) * 1000, 1)

    _queue_depth += 1
    _inflight += 1
    try:
        fut = _executor.submit(_call)
        resp = fut.result(timeout=32)
    except FuturesTimeoutError:
        return {"ok": False, "error": "LLM timeout", "session_id": session_id}
    finally:
        _inflight = max(0, _inflight - 1)
        _queue_depth = max(0, _queue_depth - 1)

    if resp.get("ok"):
        text = resp.get("text", "")
        lab_store.append_message(session_id, "assistant", text, provider=resp.get("provider"))
        lesson = _parse_lesson_tag(text)
        if lesson:
            lab_store.append_lesson({"session_id": session_id, "text": lesson, "source": "auto"})
    return {**resp, "session_id": session_id}


def bootstrap_knowledge(*, force: bool = False) -> dict[str, Any]:
    return bootstrap_system_knowledge(force=force)


def add_lesson(text: str, *, session_id: str = "", tags: list[str] | None = None) -> dict[str, Any]:
    row = {"text": text, "session_id": session_id, "tags": tags or [], "source": "manual"}
    lab_store.append_lesson(row)
    return {"ok": True, "lesson": row}


def link_checkpoint(session_id: str, checkpoint_id: str) -> dict[str, Any]:
    if not session_id:
        return {"ok": False, "error": "session_id required"}
    meta = lab_store.update_session_meta(session_id, {"checkpoint_ref": checkpoint_id})
    return {"ok": True, "session_id": session_id, "meta": meta}


def export_bundle(*, session_id: str = "") -> dict[str, Any]:
    import io
    import zipfile
    from pathlib import Path

    root = lab_store.lab_data_dir()
    buf = io.BytesIO()
    checkpoint_ref = None
    if session_id:
        meta = lab_store.read_session_meta(session_id)
        checkpoint_ref = meta.get("checkpoint_ref")
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for fp in root.rglob("*"):
            if fp.is_file():
                zf.write(fp, arcname=str(fp.relative_to(root)))
        if checkpoint_ref:
            zf.writestr(
                "checkpoint_ref.json",
                json.dumps({"checkpoint_id": checkpoint_ref, "session_id": session_id}, indent=2),
            )
    return {
        "ok": True,
        "bytes": len(buf.getvalue()),
        "data_b64": __import__("base64").b64encode(buf.getvalue()).decode(),
        "checkpoint_ref": checkpoint_ref,
    }
