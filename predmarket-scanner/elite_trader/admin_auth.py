"""Admin panel authentication — session tokens via HttpOnly cookie."""
from __future__ import annotations

import hashlib
import os
import secrets
import threading
import time
from typing import Any

_DEFAULT_PASSWORD_HASH = hashlib.sha256(b"x369").hexdigest()
_SESSION_TTL_SEC = 86400.0
_sessions: dict[str, float] = {}
_lock = threading.Lock()


def _expected_hash() -> str:
    custom = os.getenv("ADMIN_PANEL_PASSWORD_HASH", "").strip().lower()
    if custom:
        return custom
    plain = os.getenv("ADMIN_PANEL_PASSWORD", "").strip()
    if plain:
        return hashlib.sha256(plain.encode("utf-8")).hexdigest()
    return _DEFAULT_PASSWORD_HASH


def verify_password(password: str) -> bool:
    if not password:
        return False
    got = hashlib.sha256(password.encode("utf-8")).hexdigest()
    return secrets.compare_digest(got, _expected_hash())


def create_session() -> str:
    token = secrets.token_urlsafe(32)
    with _lock:
        _sessions[token] = time.time() + _SESSION_TTL_SEC
    return token


def session_valid(token: str | None) -> bool:
    if not token:
        return False
    now = time.time()
    with _lock:
        exp = _sessions.get(token)
        if not exp:
            return False
        if exp < now:
            _sessions.pop(token, None)
            return False
        _sessions[token] = now + _SESSION_TTL_SEC
        return True


def revoke_session(token: str | None) -> None:
    if not token:
        return
    with _lock:
        _sessions.pop(token, None)


def auth_status(token: str | None) -> dict[str, Any]:
    return {"authenticated": session_valid(token)}
