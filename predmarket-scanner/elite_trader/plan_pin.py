"""Strateji plan panosu — 4 haneli uygulama kodu (yalnızca panelden değişir)."""
from __future__ import annotations

import json
import re
import secrets
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
_PIN_PATH = _ROOT / "data" / "panel_plan_pin.json"
_DEFAULT_PIN = "0346"


def _load() -> dict[str, Any]:
    if not _PIN_PATH.is_file():
        return {"pin": _DEFAULT_PIN, "updated_at": None}
    try:
        return json.loads(_PIN_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"pin": _DEFAULT_PIN, "updated_at": None}


def _save(data: dict[str, Any]) -> None:
    _PIN_PATH.parent.mkdir(parents=True, exist_ok=True)
    _PIN_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def verify_pin(pin: str) -> bool:
    if not re.fullmatch(r"\d{4}", str(pin or "").strip()):
        return False
    stored = str(_load().get("pin") or _DEFAULT_PIN).strip()
    return secrets.compare_digest(str(pin).strip(), stored)


def change_pin(old_pin: str, new_pin: str) -> dict[str, Any]:
    old = str(old_pin or "").strip()
    new = str(new_pin or "").strip()
    if not verify_pin(old):
        return {"ok": False, "error": "Mevcut kod yanlış"}
    if not re.fullmatch(r"\d{4}", new):
        return {"ok": False, "error": "Yeni kod 4 haneli olmalı"}
    if new == old:
        return {"ok": False, "error": "Yeni kod eskisiyle aynı olamaz"}
    from datetime import datetime, timezone

    _save({"pin": new, "updated_at": datetime.now(timezone.utc).isoformat()})
    return {"ok": True, "message": "Uygulama kodu güncellendi (plan panosu)."}


def pin_status() -> dict[str, Any]:
    return {
        "configured": True,
        "changeable_from": "strategy_plan_panel_only",
        "digits": 4,
    }
