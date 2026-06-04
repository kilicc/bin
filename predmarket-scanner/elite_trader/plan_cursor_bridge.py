"""Plan panel → Cursor (cursor-agent CLI + IDE hesap senkronu)."""
from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

from elite_trader.plan_cursor_account import (
    account_status,
    cli_agent_path,
    cli_available,
    sync_cli_from_ide,
)
from elite_trader.plan_cursor_transcript import (
    load_transcript_turns,
    resolve_transcript_path,
    transcript_status,
)

_ROOT = Path(__file__).resolve().parent.parent
_SESSION_PATH = _ROOT / "data/plan_cursor_session.json"
_NODE_SCRIPT = _ROOT / "scripts/cursor-plan/plan_agent.mjs"
_NODE_MODULES = _ROOT / "scripts/cursor-plan/node_modules"


def resolve_cursor_api_key() -> str:
    k = (os.getenv("CURSOR_API_KEY") or os.getenv("CURSOR_AGENT_API_KEY") or "").strip()
    if (k.startswith("cursor_") or k.startswith("crsr_")) and len(k) > 24:
        return k
    return ""


def _node_bin() -> str:
    for cand in (
        os.getenv("ELITE_PLAN_NODE"),
        "/Applications/Cursor.app/Contents/Resources/app/resources/helpers/node",
        "node",
    ):
        if not cand:
            continue
        p = Path(cand)
        if p.is_file() or subprocess.run(
            ["which", cand], capture_output=True, text=True
        ).returncode == 0:
            return str(cand)
    return "node"


def sdk_ready() -> bool:
    return _NODE_SCRIPT.is_file() and (_NODE_MODULES / "@cursor/sdk").is_dir()


def load_session() -> dict[str, Any]:
    if not _SESSION_PATH.is_file():
        return {}
    try:
        return json.loads(_SESSION_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_session(data: dict[str, Any]) -> None:
    _SESSION_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {**data, "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    _SESSION_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _ensure_account_linked() -> dict[str, Any]:
    acc = account_status()
    if acc.get("cli_logged_in"):
        return {"ok": True, "account": acc}
    if acc.get("ide_logged_in"):
        return {**sync_cli_from_ide(), "account": account_status()}
    return {"ok": False, "account": acc}


def merge_histories(
    panel_history: list[dict[str, str]] | None,
    *,
    max_turns: int = 16,
) -> list[dict[str, str]]:
    transcript = load_transcript_turns(max_turns=max_turns)
    panel: list[dict[str, str]] = []
    for h in panel_history or []:
        role = h.get("role")
        content = (h.get("content") or "").strip()
        if not content:
            continue
        if role == "user":
            panel.append({"role": "user", "content": content[:3500]})
        elif role in ("assistant", "danışman", "advisor"):
            panel.append({"role": "assistant", "content": content[:3500]})
    if not transcript:
        return panel[-max_turns:]
    if not panel:
        return transcript[-max_turns:]
    merged = list(transcript)
    for p in panel:
        if merged and merged[-1] == p:
            continue
        if any(m.get("content") == p.get("content") for m in merged[-4:]):
            continue
        merged.append(p)
    return merged[-max_turns:]


def format_messages_for_agent(
    system: str,
    context: str,
    prompt: str,
    history: list[dict[str, str]],
) -> str:
    lines = [system.strip(), "", "[Sistem verisi — canlı panel]", context[:14000], ""]
    if history:
        lines.append("[Önceki konuşma — Cursor IDE + panel]")
        for h in history[-12:]:
            who = "Kullanıcı" if h["role"] == "user" else "Danışman"
            lines.append(f"{who}: {h['content'][:2500]}")
        lines.append("")
    lines.append(f"[Yeni mesaj — panel]\n{prompt.strip()}")
    lines.append(
        "\nYanıtı Türkçe, samimi ve net ver. Sonunda 1–4 maddelik «Yapılacaklar» özeti ekle. "
        "Kod veya env değişken adı yazma."
    )
    return "\n".join(lines)


def _account_label(acc: dict[str, Any]) -> str:
    email = acc.get("email") or ""
    tier = (acc.get("tier") or "").strip()
    if email:
        t = f" ({tier})" if tier and tier.lower() != "unknown" else ""
        return f"{email}{t}"
    return ""


def cursor_status() -> dict[str, Any]:
    llm_on = os.getenv("ELITE_PLAN_LLM", "1").strip().lower() not in ("0", "false", "no")
    ts = transcript_status()
    sess = load_session()
    acc = account_status()
    key = resolve_cursor_api_key()

    if not llm_on:
        return {
            "backend": "cursor",
            "mode": "local",
            "llm_active": False,
            "label": "Yerel danışman",
            "hint": "Cursor LLM kapalı (ELITE_PLAN_LLM=0).",
            "account": acc,
            "transcript": ts,
            "session": sess,
        }

    lbl = _account_label(acc)
    if acc.get("cli_logged_in") or acc.get("ide_logged_in"):
        return {
            "backend": "cursor",
            "mode": "cursor",
            "llm_active": True,
            "label": "Cursor danışman",
            "hint": (
                f"Hesap bağlı{': ' + lbl if lbl else ''}"
                + (" · IDE transcript" if ts.get("bound") else "")
                + "."
            ),
            "account": acc,
            "transcript": ts,
            "transcript_bound": ts.get("bound"),
            "session": sess,
            "auth_source": "cli" if acc.get("cli_logged_in") else "ide",
        }

    if key:
        return {
            "backend": "cursor",
            "mode": "cursor",
            "llm_active": True,
            "label": "Cursor · API anahtarı",
            "hint": "CURSOR_API_KEY ile bağlı.",
            "account": acc,
            "transcript": ts,
        }

    return {
        "backend": "cursor",
        "mode": "cursor_context",
        "llm_active": False,
        "label": "Cursor · hesap bekleniyor",
        "hint": (
            "Cursor IDE açık ve giriş yapılı olmalı; panel ilk mesajda hesabı otomatik bağlar. "
            f"{lbl or 'E-posta bulunamadı — IDE’de oturum açın.'}"
        ),
        "account": acc,
        "transcript": ts,
        "transcript_bound": ts.get("bound"),
    }


def _cursor_cli_reply(
    user_message: str,
    *,
    api_key: str = "",
) -> tuple[str | None, str | None]:
    """cursor-agent --print; (metin, hata)."""
    if not cli_available():
        return None, "cursor-agent kurulu değil (~/.local/bin/cursor-agent)"

    link = _ensure_account_linked()
    if not link.get("ok") and not api_key:
        return None, link.get("error") or "Cursor hesabı bağlanamadı"

    model = (os.getenv("ELITE_PLAN_CURSOR_MODEL") or "auto").strip()
    timeout = int(os.getenv("ELITE_PLAN_CURSOR_TIMEOUT_SEC", "180") or "180")
    sess = load_session()
    chat_id = sess.get("cli_chat_id")

    cmd = [
        cli_agent_path(),
        "-p",
        "--mode",
        "ask",
        "--trust",
        "--workspace",
        str(_ROOT),
        "--output-format",
        "text",
    ]
    if model and model != "auto":
        cmd.extend(["--model", model])
    if api_key:
        cmd.extend(["--api-key", api_key])
    if chat_id:
        cmd.extend(["--resume", str(chat_id)])
    elif sess.get("cli_continue"):
        cmd.append("--continue")

    env = {**os.environ, "NO_OPEN_BROWSER": "1"}
    try:
        proc = subprocess.run(
            cmd,
            input=user_message,
            capture_output=True,
            text=True,
            timeout=max(45, timeout),
            cwd=str(_ROOT),
            env=env,
        )
    except subprocess.TimeoutExpired:
        return None, "zaman aşımı"
    except Exception as exc:
        return None, str(exc)[:200]

    text = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    if proc.returncode != 0:
        return None, (err or text or f"exit {proc.returncode}")[:400]
    if not text:
        return None, (err or "boş yanıt")[:400]
    save_session({**sess, "cli_continue": True})
    return text, None


def _cursor_sdk_reply(
    user_message: str,
    *,
    api_key: str,
) -> tuple[str | None, str | None]:
    if not api_key or not sdk_ready():
        return None, "sdk unavailable"
    sess = load_session()
    model = (os.getenv("ELITE_PLAN_CURSOR_MODEL") or "composer-2.5-fast").strip()
    timeout = int(os.getenv("ELITE_PLAN_CURSOR_TIMEOUT_SEC", "180") or "180")
    payload = {
        "apiKey": api_key,
        "cwd": str(_ROOT),
        "model": model,
        "agentId": sess.get("agent_id"),
        "userMessage": user_message,
    }
    try:
        proc = subprocess.run(
            [_node_bin(), str(_NODE_SCRIPT)],
            input=json.dumps(payload, ensure_ascii=False),
            capture_output=True,
            text=True,
            timeout=max(30, timeout),
            cwd=str(_ROOT),
            env={**os.environ, "CURSOR_API_KEY": api_key},
        )
    except Exception as exc:
        return None, str(exc)[:200]
    lines = [l for l in (proc.stdout or "").strip().splitlines() if l.strip()]
    if not lines:
        return None, (proc.stderr or "boş")[:300]
    try:
        data = json.loads(lines[-1])
    except json.JSONDecodeError:
        return None, "json"
    if not data.get("ok"):
        return None, str(data.get("error") or "error")[:200]
    aid = data.get("agent_id")
    if aid:
        save_session({**sess, "agent_id": aid})
    return (data.get("text") or "").strip() or None, None


def cursor_reply(
    prompt: str,
    *,
    system: str,
    context: str,
    history: list[dict[str, str]] | None = None,
) -> tuple[str | None, dict[str, Any]]:
    status = cursor_status()
    if not status.get("llm_active"):
        link = _ensure_account_linked()
        if link.get("ok"):
            status = cursor_status()
        if not status.get("llm_active"):
            return None, status

    merged = merge_histories(history)
    user_message = format_messages_for_agent(system, context, prompt, merged)
    api_key = resolve_cursor_api_key()

    text, err = _cursor_cli_reply(user_message, api_key=api_key)
    if not text and api_key:
        text, err2 = _cursor_sdk_reply(user_message, api_key=api_key)
        err = err2 or err

    if text:
        acc = account_status()
        status = {
            **status,
            "llm_active": True,
            "mode": "cursor",
            "label": "Cursor danışman",
            "hint": f"Hesap: {_account_label(acc) or 'bağlı'} · canlı yanıt.",
            "account": acc,
        }
        return text, status

    status = {
        **status,
        "llm_active": False,
        "hint": f"Cursor yanıt veremedi: {err or 'bilinmeyen'} — yerel danışman.",
    }
    return None, status
