#!/usr/bin/env python3
"""Eski mod ID'lerini yeni 5 mod yapısına taşır."""
from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
BACKUP = ROOT / "data" / "backups" / f"pre_mode_rename_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"

MAP = {
    "live_9005": "sentinel",
    "evren_evrim": "evrim",
    "evren_simsek": "berserk",
    "evren_avci": "hunter",
    "evren_kalkan": "chop_master",
}


def _remap_dict_keys(obj: dict, depth: int = 0) -> dict:
    if depth > 8:
        return obj
    out: dict = {}
    for k, v in obj.items():
        nk = MAP.get(k, k)
        if isinstance(v, dict):
            out[nk] = _remap_dict_keys(v, depth + 1)
        elif isinstance(v, list):
            out[nk] = v
        else:
            out[nk] = v
    return out


def _remap_str_fields(row: dict, fields: tuple[str, ...]) -> None:
    for f in fields:
        if f in row and row[f] in MAP:
            row[f] = MAP[row[f]]


def migrate_parallel_universes() -> None:
    path = ROOT / "data" / "parallel_universes.json"
    if not path.is_file():
        return
    st = json.loads(path.read_text(encoding="utf-8"))
    universes = st.get("universes") or {}
    new_u: dict = {}
    caps = st.get("capital_by_mode") or {}
    new_caps: dict = {}
    for old, new in MAP.items():
        if old in universes:
            book = universes[old]
            for pos in book.get("open") or []:
                _remap_str_fields(
                    pos,
                    ("panel_mode", "universe_id", "execution_mode_at_open", "signal_source"),
                )
            for pos in book.get("closed") or []:
                _remap_str_fields(
                    pos,
                    (
                        "panel_mode",
                        "universe_id",
                        "execution_mode_at_close",
                        "signal_source",
                    ),
                )
            new_u[new] = book
        if old in caps:
            new_caps[new] = caps[old]
    for mid in ("evrim", "berserk", "hunter", "chop_master", "sentinel"):
        new_u.setdefault(mid, {"open": [], "closed": [], "next_id": 1, "session_start": 5000})
        new_caps.setdefault(mid, 5000)
    st["universes"] = new_u
    st["capital_by_mode"] = new_caps
    path.write_text(json.dumps(st, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def migrate_panel_state() -> None:
    path = ROOT / "data" / "panel_strategy_state.json"
    st = {"execution_mode": "evrim", "view_mode": "evrim", "current_mode": "evrim"}
    if path.is_file():
        try:
            old = json.loads(path.read_text(encoding="utf-8"))
            ex = MAP.get(old.get("execution_mode") or "", "evrim")
            vw = MAP.get(old.get("view_mode") or ex, ex)
            st = {
                "execution_mode": ex,
                "view_mode": vw,
                "current_mode": ex,
                "active_futures_mode": ex,
                "last_execution_change_at": old.get("last_execution_change_at"),
                "last_execution_note": (old.get("last_execution_note") or "") + " [migrated v2]",
            }
        except Exception:
            pass
    path.write_text(json.dumps(st, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def migrate_mode_profiles() -> None:
    from elite_trader.mode_profiles import _BUILTIN_MODES

    path = ROOT / "data" / "mode_profiles.json"
    path.write_text(
        json.dumps(
            {
                "version": 2,
                "note": "5 mod paralel evren — migrated",
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "modes": _BUILTIN_MODES,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def main() -> None:
    BACKUP.mkdir(parents=True, exist_ok=True)
    for name in (
        "parallel_universes.json",
        "panel_strategy_state.json",
        "mode_profiles.json",
        "evrim_training_state.json",
        "evrim_adaptive_state.json",
    ):
        src = ROOT / "data" / name
        if src.is_file():
            shutil.copy2(src, BACKUP / name)
    migrate_parallel_universes()
    migrate_panel_state()
    migrate_mode_profiles()
    print(f"OK — backup: {BACKUP}")


if __name__ == "__main__":
    main()
