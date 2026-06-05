"""Cursor IDE hesabı → cursor-agent CLI oturumu."""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
from pathlib import Path
from typing import Any

_IDE_DB = Path.home() / "Library/Application Support/Cursor/User/globalStorage/state.vscdb"
_CLI_AUTH = Path.home() / ".cursor/auth.json"
_CURSOR_AGENT = Path.home() / ".local/bin/cursor-agent"
_ACCOUNT_META = Path(__file__).resolve().parent.parent / "data/plan_cursor_account.json"


def _read_ide_row(key: str) -> str:
    if not _IDE_DB.is_file():
        return ""
    try:
        con = sqlite3.connect(str(_IDE_DB))
        row = con.execute(
            "SELECT value FROM ItemTable WHERE key=?", (key,)
        ).fetchone()
        con.close()
        return (row[0] if row else "") or ""
    except Exception:
        return ""


def load_ide_account() -> dict[str, Any]:
    """Açık Cursor IDE oturumundaki giriş bilgisi."""
    email = _read_ide_row("cursorAuth/cachedEmail").strip()
    tier = _read_ide_row("cursorAuth/stripeMembershipType").strip() or "unknown"
    access = _read_ide_row("cursorAuth/accessToken").strip()
    refresh = _read_ide_row("cursorAuth/refreshToken").strip()
    return {
        "email": email or None,
        "tier": tier,
        "ide_logged_in": bool(access and refresh),
        "has_access_token": bool(access),
        "has_refresh_token": bool(refresh),
    }


def sync_cli_from_ide(*, force: bool = False) -> dict[str, Any]:
    """
    IDE token'larını ~/.cursor/auth.json içine yazar (cursor-agent aynı hesap).
    Token dosyaya yazılmaz — sadece CLI auth dosyası güncellenir.
    """
    acc = load_ide_account()
    if not acc.get("ide_logged_in"):
        return {
            "ok": False,
            "error": "Cursor IDE oturumu bulunamadı (giriş yapılmamış).",
            **acc,
        }
    access = _read_ide_row("cursorAuth/accessToken").strip()
    refresh = _read_ide_row("cursorAuth/refreshToken").strip()
    existing: dict[str, Any] = {}
    if _CLI_AUTH.is_file() and not force:
        try:
            existing = json.loads(_CLI_AUTH.read_text(encoding="utf-8"))
        except Exception:
            existing = {}
        if (
            existing.get("accessToken") == access
            and existing.get("refreshToken") == refresh
        ):
            st = cli_auth_status()
            if st.get("logged_in"):
                return {"ok": True, "synced": False, "already": True, **acc, **st}

    payload = {
        "accessToken": access,
        "refreshToken": refresh,
        "apiKey": existing.get("apiKey"),
        "bedrockCredentials": existing.get("bedrockCredentials"),
    }
    _CLI_AUTH.parent.mkdir(parents=True, exist_ok=True)
    _CLI_AUTH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    try:
        os.chmod(_CLI_AUTH, 0o600)
    except OSError:
        pass

    meta = {
        "email": acc.get("email"),
        "tier": acc.get("tier"),
        "synced_at": __import__("time").strftime("%Y-%m-%dT%H:%M:%SZ", __import__("time").gmtime()),
    }
    _ACCOUNT_META.parent.mkdir(parents=True, exist_ok=True)
    _ACCOUNT_META.write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    st = cli_auth_status()
    return {"ok": st.get("logged_in", False), "synced": True, **acc, **st}


def cli_agent_path() -> str:
    if _CURSOR_AGENT.is_file():
        return str(_CURSOR_AGENT)
    return "cursor-agent"


def cli_available() -> bool:
    p = Path(cli_agent_path())
    return p.is_file() or subprocess.run(
        ["which", "cursor-agent"], capture_output=True
    ).returncode == 0


def cli_auth_status() -> dict[str, Any]:
    """cursor-agent status çıktısı."""
    if not cli_available():
        return {"logged_in": False, "cli_installed": False}
    try:
        proc = subprocess.run(
            [cli_agent_path(), "status"],
            capture_output=True,
            text=True,
            timeout=25,
            env={**os.environ, "NO_OPEN_BROWSER": "1"},
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        logged = "not logged in" not in out.lower()
        email = None
        for line in out.splitlines():
            low = line.lower()
            if "email" in low and "not logged" not in low:
                email = line.split(":", 1)[-1].strip() or None
        tier = None
        for line in out.splitlines():
            if "subscription" in line.lower() or "tier" in line.lower():
                tier = line.split(":", 1)[-1].strip() or None
        return {
            "logged_in": logged,
            "cli_installed": True,
            "email": email,
            "tier": tier,
            "raw": out[:500] if not logged else None,
        }
    except Exception as exc:
        return {"logged_in": False, "cli_installed": True, "error": str(exc)[:200]}


def account_status() -> dict[str, Any]:
    """Panel rozeti için birleşik hesap durumu."""
    ide = load_ide_account()
    cli = cli_auth_status()
    meta: dict[str, Any] = {}
    if _ACCOUNT_META.is_file():
        try:
            meta = json.loads(_ACCOUNT_META.read_text(encoding="utf-8"))
        except Exception:
            pass
    email = cli.get("email") or ide.get("email") or meta.get("email")
    tier = cli.get("tier") or ide.get("tier") or meta.get("tier")
    linked = bool(cli.get("logged_in")) or bool(ide.get("ide_logged_in"))
    return {
        "email": email,
        "tier": tier,
        "ide_logged_in": ide.get("ide_logged_in"),
        "cli_logged_in": cli.get("logged_in"),
        "cli_installed": cli.get("cli_installed", cli_available()),
        "linked": linked,
        "can_run_agent": bool(cli.get("logged_in")),
    }
