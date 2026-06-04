"""Mod-özel giriş motorları — paper laboratuvar."""
from __future__ import annotations

from typing import Any

from elite_trader.mode_registry import resolve_mode_id

_ENGINES: dict[str, str] = {
    "berserk": "berserk_engine",
    "berserk2": "berserk2_engine",
    "hunter": "hunter_engine",
    "chop_master": "chop_master_engine",
    "sentinel": "sentinel_engine",
    "mega": "mega_engine",
}


def evaluate_entry(
    mode_id: str,
    signal: dict[str, Any],
    ctx: dict[str, Any] | None = None,
) -> tuple[bool, str]:
    """Mod özel giriş — evrim bu katmandan geçmez (evrim_entry_gate ayrı)."""
    mid = resolve_mode_id(mode_id)
    if mid == "evrim":
        return True, ""
    mod = _ENGINES.get(mid)
    if not mod:
        return True, ""
    import importlib

    eng = importlib.import_module(f"elite_trader.mode_engines.{mod}")
    return eng.evaluate(signal, ctx or {})
