"""Strateji plan — mod başına ayrı sohbet alanları (Cursor yeni proje gibi)."""
from __future__ import annotations

import json
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from elite_trader.plan_modes import (
    INSIGHTS_CHAT_ID,
    INSIGHTS_TITLE,
    all_plan_mode_ids,
    normalize_mode_id,
)

_ROOT = Path(__file__).resolve().parent.parent
_CHATS_ROOT = _ROOT / "data" / "plan_chats"
_LEGACY_INDEX = _CHATS_ROOT / "index.json"
_LEGACY_DONE = _CHATS_ROOT / "_legacy_migrated.done"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _mode_dir(mode_id: str) -> Path:
    mid = normalize_mode_id(mode_id)
    d = _CHATS_ROOT / mid
    d.mkdir(parents=True, exist_ok=True)
    return d


def _index_path(mode_id: str) -> Path:
    return _mode_dir(mode_id) / "index.json"


def _chat_path(mode_id: str, chat_id: str) -> Path:
    safe = re.sub(r"[^\w\-]", "_", chat_id)[:80]
    return _mode_dir(mode_id) / f"{safe}.json"


def _migrate_legacy() -> None:
    """Eski düz plan_chats/*.json → mod klasörlerine."""
    if _LEGACY_DONE.is_file():
        return
    if not _LEGACY_INDEX.is_file():
        _LEGACY_DONE.write_text("ok\n", encoding="utf-8")
        return
    try:
        idx = json.loads(_LEGACY_INDEX.read_text(encoding="utf-8"))
    except Exception:
        return
    for meta in idx.get("chats") or []:
        cid = meta.get("id")
        if not cid:
            continue
        safe_cid = re.sub(r"[^\w\-]", "_", cid)[:80]
        old = _CHATS_ROOT / f"{safe_cid}.json"
        if not old.is_file():
            continue
        try:
            chat = json.loads(old.read_text(encoding="utf-8"))
        except Exception:
            continue
        mid = normalize_mode_id(chat.get("mode_id") or meta.get("mode_id"))
        if cid == INSIGHTS_CHAT_ID and not chat.get("mode_id"):
            for m in all_plan_mode_ids():
                _copy_insights_seed(m, chat)
            continue
        chat["mode_id"] = mid
        _save_chat_file(mid, chat)
        _upsert_index_meta(mid, chat)
    bak = _CHATS_ROOT / "_legacy_migrated"
    bak.mkdir(parents=True, exist_ok=True)
    try:
        if _LEGACY_INDEX.is_file():
            shutil.move(str(_LEGACY_INDEX), str(bak / "index.json"))
    except Exception:
        pass
    legacy_ins = _CHATS_ROOT / f"{INSIGHTS_CHAT_ID}.json"
    if legacy_ins.is_file():
        try:
            shutil.move(str(legacy_ins), str(bak / f"{INSIGHTS_CHAT_ID}.json"))
        except Exception:
            pass
    _LEGACY_DONE.write_text("ok\n", encoding="utf-8")


def _copy_insights_seed(mode_id: str, template: dict[str, Any]) -> None:
    chat = {
        "id": INSIGHTS_CHAT_ID,
        "title": INSIGHTS_TITLE,
        "pinned": True,
        "permanent": True,
        "mode_id": mode_id,
        "messages": list(template.get("messages") or [])[:20],
        "created_at": template.get("created_at") or _now_iso(),
        "updated_at": _now_iso(),
    }
    _save_chat_file(mode_id, chat)
    _upsert_index_meta(mode_id, chat)


def _load_index(mode_id: str, *, run_migrate: bool = True) -> dict[str, Any]:
    if run_migrate:
        _migrate_legacy()
    mid = normalize_mode_id(mode_id)
    p = _index_path(mid)
    if not p.is_file():
        idx: dict[str, Any] = {"mode_id": mid, "chats": [], "active_chat_id": INSIGHTS_CHAT_ID}
        return _ensure_insights_in_index(mid, idx)
    try:
        idx = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        idx = {"mode_id": mid, "chats": [], "active_chat_id": INSIGHTS_CHAT_ID}
    return _ensure_insights_in_index(mid, idx)


def _save_index(mode_id: str, index: dict[str, Any]) -> None:
    index["mode_id"] = normalize_mode_id(mode_id)
    _index_path(mode_id).write_text(
        json.dumps(index, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _ensure_insights_in_index(mode_id: str, index: dict[str, Any]) -> dict[str, Any]:
    chats = list(index.get("chats") or [])
    ids = {c.get("id") for c in chats}
    if INSIGHTS_CHAT_ID not in ids:
        chats.insert(
            0,
            {
                "id": INSIGHTS_CHAT_ID,
                "title": INSIGHTS_TITLE,
                "pinned": True,
                "permanent": True,
                "mode_id": mode_id,
                "created_at": _now_iso(),
                "updated_at": _now_iso(),
            },
        )
        index["chats"] = chats
        if not _chat_path(mode_id, INSIGHTS_CHAT_ID).is_file():
            _save_chat_file(
                mode_id,
                {
                    "id": INSIGHTS_CHAT_ID,
                    "title": INSIGHTS_TITLE,
                    "pinned": True,
                    "permanent": True,
                    "mode_id": mode_id,
                    "messages": [],
                    "created_at": _now_iso(),
                    "updated_at": _now_iso(),
                },
            )
    return index


def _save_chat_file(mode_id: str, chat: dict[str, Any]) -> None:
    chat["mode_id"] = normalize_mode_id(mode_id)
    chat["updated_at"] = _now_iso()
    _chat_path(mode_id, chat["id"]).write_text(
        json.dumps(chat, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _upsert_index_meta(mode_id: str, chat: dict[str, Any]) -> None:
    index = _load_index(mode_id, run_migrate=False)
    chats = list(index.get("chats") or [])
    found = False
    for c in chats:
        if c.get("id") == chat["id"]:
            c["title"] = chat.get("title")
            c["updated_at"] = chat.get("updated_at")
            c["mode_id"] = mode_id
            found = True
            break
    if not found:
        chats.append(
            {
                "id": chat["id"],
                "title": chat.get("title"),
                "pinned": chat.get("pinned"),
                "permanent": chat.get("permanent"),
                "mode_id": mode_id,
                "created_at": chat.get("created_at"),
                "updated_at": chat.get("updated_at"),
            }
        )
    index["chats"] = chats
    _save_index(mode_id, index)


def _load_chat(mode_id: str, chat_id: str) -> dict[str, Any] | None:
    mid = normalize_mode_id(mode_id)
    p = _chat_path(mid, chat_id)
    if not p.is_file():
        if chat_id == INSIGHTS_CHAT_ID:
            _ensure_insights_in_index(mid, {"mode_id": mid, "chats": []})
            return _load_chat(mid, chat_id)
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def list_chats(mode_id: str) -> list[dict[str, Any]]:
    mid = normalize_mode_id(mode_id)
    index = _load_index(mid)
    out: list[dict[str, Any]] = []
    for meta in index.get("chats") or []:
        cid = meta.get("id")
        if not cid:
            continue
        full = _load_chat(mid, cid)
        out.append(
            {
                "id": cid,
                "title": meta.get("title") or (full or {}).get("title") or "Sohbet",
                "pinned": bool(meta.get("pinned") or cid == INSIGHTS_CHAT_ID),
                "permanent": bool(meta.get("permanent") or cid == INSIGHTS_CHAT_ID),
                "updated_at": meta.get("updated_at") or (full or {}).get("updated_at"),
                "message_count": len((full or {}).get("messages") or []),
                "mode_id": mid,
            }
        )
    pinned = [c for c in out if c.get("pinned")]
    rest = sorted(
        [c for c in out if not c.get("pinned")],
        key=lambda c: c.get("updated_at") or "",
        reverse=True,
    )
    return pinned + rest


def get_chat(mode_id: str, chat_id: str) -> dict[str, Any] | None:
    mid = normalize_mode_id(mode_id)
    chat = _load_chat(mid, chat_id)
    if not chat:
        return None
    return {
        "id": chat["id"],
        "title": chat.get("title") or "Sohbet",
        "pinned": chat.get("pinned") or chat["id"] == INSIGHTS_CHAT_ID,
        "permanent": chat.get("permanent") or chat["id"] == INSIGHTS_CHAT_ID,
        "mode_id": mid,
        "messages": list(chat.get("messages") or []),
        "created_at": chat.get("created_at"),
        "updated_at": chat.get("updated_at"),
    }


def create_chat(*, mode_id: str, title: str | None = None) -> dict[str, Any]:
    mid = normalize_mode_id(mode_id)
    cid = str(uuid.uuid4())[:12]
    t = (title or "").strip() or "Yeni sohbet"
    chat = {
        "id": cid,
        "title": t,
        "pinned": False,
        "permanent": False,
        "mode_id": mid,
        "messages": [],
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }
    _save_chat_file(mid, chat)
    _upsert_index_meta(mid, chat)
    index = _load_index(mid)
    index["active_chat_id"] = cid
    _save_index(mid, index)
    return get_chat(mid, cid) or chat


def delete_chat(mode_id: str, chat_id: str) -> dict[str, Any]:
    if chat_id == INSIGHTS_CHAT_ID:
        return {"ok": False, "error": "Anlık öneriler sohbeti silinemez."}
    mid = normalize_mode_id(mode_id)
    if not _load_chat(mid, chat_id):
        return {"ok": False, "error": "Sohbet bulunamadı"}
    p = _chat_path(mid, chat_id)
    if p.is_file():
        p.unlink()
    index = _load_index(mid)
    index["chats"] = [c for c in (index.get("chats") or []) if c.get("id") != chat_id]
    if index.get("active_chat_id") == chat_id:
        index["active_chat_id"] = INSIGHTS_CHAT_ID
    _save_index(mid, index)
    return {"ok": True}


def history_for_llm(mode_id: str, chat_id: str, *, max_turns: int = 24) -> list[dict[str, str]]:
    chat = _load_chat(normalize_mode_id(mode_id), chat_id)
    if not chat:
        return []
    out: list[dict[str, str]] = []
    for m in (chat.get("messages") or [])[-max_turns:]:
        role = m.get("role")
        content = (m.get("content") or "").strip()
        if not content:
            continue
        if role == "user":
            out.append({"role": "user", "content": content[:3500]})
        elif role in ("assistant", "bot", "danışman"):
            out.append({"role": "assistant", "content": content[:3500]})
    return out


def append_messages(
    mode_id: str,
    chat_id: str,
    *,
    user: str | None = None,
    assistant: str | None = None,
    system: str | None = None,
) -> dict[str, Any]:
    mid = normalize_mode_id(mode_id)
    chat = _load_chat(mid, chat_id)
    if not chat:
        if chat_id == INSIGHTS_CHAT_ID:
            _ensure_insights_in_index(mid, {"mode_id": mid, "chats": []})
            chat = _load_chat(mid, chat_id)
        if not chat:
            return {"ok": False, "error": "Sohbet bulunamadı"}
    msgs = list(chat.get("messages") or [])
    if system:
        msgs.append({"role": "system", "content": system[:2000], "at": _now_iso()})
    if user:
        msgs.append({"role": "user", "content": user, "at": _now_iso()})
        if chat_id != INSIGHTS_CHAT_ID and chat.get("title") in (None, "", "Yeni sohbet"):
            chat["title"] = (user[:48] + "…") if len(user) > 48 else user
    if assistant:
        msgs.append({"role": "assistant", "content": assistant, "at": _now_iso()})
    chat["messages"] = msgs[-500:]
    chat["mode_id"] = mid
    _save_chat_file(mid, chat)
    _upsert_index_meta(mid, chat)
    index = _load_index(mid)
    index["active_chat_id"] = chat_id
    _save_index(mid, index)
    return {"ok": True, "chat_id": chat_id, "mode_id": mid}


def export_chat_markdown(mode_id: str, chat_id: str) -> tuple[bytes, str]:
    chat = _load_chat(normalize_mode_id(mode_id), chat_id)
    if not chat:
        return b"", "empty.md"
    lines = [
        f"# {chat.get('title') or 'Sohbet'}",
        f"Mod: {chat.get('mode_id')}",
        f"Güncelleme: {chat.get('updated_at', '')}",
        "",
    ]
    for m in chat.get("messages") or []:
        who = {"user": "Siz", "assistant": "Danışman", "system": "Sistem"}.get(
            m.get("role"), m.get("role")
        )
        lines.extend([f"## {who}", "", m.get("content") or "", ""])
    body = "\n".join(lines).encode("utf-8-sig")
    safe = re.sub(r"[^\w\-]", "_", (chat.get("title") or "sohbet")[:30])
    mid = normalize_mode_id(mode_id)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    return body, f"plan_{mid}_{safe}_{ts}.md"


def export_chat_json(mode_id: str, chat_id: str) -> tuple[bytes, str]:
    chat = _load_chat(normalize_mode_id(mode_id), chat_id)
    if not chat:
        return b"{}", "empty.json"
    body = json.dumps(chat, ensure_ascii=False, indent=2).encode("utf-8")
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    return body, f"plan_{normalize_mode_id(mode_id)}_{chat_id}_{ts}.json"
