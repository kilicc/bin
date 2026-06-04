"""
Sistem checkpoint MD — restart ve ayar değişikliklerinde kalıcı kayıt.

- Eski dosyalar silinmez; her olay yeni isimli .md üretir.
- Dosya adı olay + ayar slug içerir (kolay arama / geri dönüş).
- MD içeriği Cursor'a okutulduğunda o ana dönmek için yeterli bağlam taşır.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
CHECKPOINT_DIR = _ROOT / "data" / "reports" / "checkpoints"
INDEX_PATH = CHECKPOINT_DIR / "index.json"
_MAX_INDEX = 500


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _slug(text: str, max_len: int = 56) -> str:
    t = re.sub(r"[^a-zA-Z0-9]+", "_", (text or "unknown").strip().lower())
    t = t.strip("_")
    return (t[:max_len] if t else "unknown")


def _safe_filename(name: str) -> str | None:
    if not name or ".." in name or "/" in name or "\\" in name:
        return None
    if not re.fullmatch(r"[a-zA-Z0-9_\-]+\.md", name):
        return None
    path = CHECKPOINT_DIR / name
    try:
        path.resolve().relative_to(CHECKPOINT_DIR.resolve())
    except ValueError:
        return None
    return name if path.is_file() else None


def _load_index() -> dict[str, Any]:
    if not INDEX_PATH.is_file():
        return {"checkpoints": [], "updated_at": None}
    try:
        return json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"checkpoints": [], "updated_at": None}


def _save_index(data: dict[str, Any]) -> None:
    CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = _now_iso()
    cps = data.get("checkpoints") or []
    if len(cps) > _MAX_INDEX:
        data["checkpoints"] = cps[-_MAX_INDEX:]
    INDEX_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _collect_state_snapshot(extra: dict[str, Any] | None = None) -> dict[str, Any]:
    snap: dict[str, Any] = {"collected_at": _now_iso()}
    paths = {
        "panel_strategy_state": _ROOT / "data" / "panel_strategy_state.json",
        "mode_profiles": _ROOT / "data" / "mode_profiles.json",
        "evrim_config_versions": _ROOT / "data" / "evrim_config_versions.json",
        "evrim_persistent_learning": _ROOT / "data" / "evrim_persistent_learning.json",
        "parallel_universes_summary": _ROOT / "data" / "parallel_universes.json",
    }
    for key, path in paths.items():
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if key == "parallel_universes_summary" and isinstance(data, dict):
                uni = data.get("universes") or {}
                snap[key] = {
                    k: {
                        "open": len((v or {}).get("open") or []),
                        "closed": len((v or {}).get("closed") or []),
                    }
                    for k, v in uni.items()
                }
            else:
                snap[key] = data
        except Exception as exc:
            snap[key] = {"error": str(exc)}
    try:
        from elite_trader.panel_strategy import (
            active_execution_mode,
            active_futures_mode,
            active_view_mode,
            panel_strategy_snapshot,
        )

        snap["runtime"] = {
            "execution_mode": active_execution_mode(),
            "view_mode": active_view_mode(),
            "active_futures_mode": active_futures_mode(),
            "panel_strategy": panel_strategy_snapshot(),
        }
    except Exception as exc:
        snap["runtime_error"] = str(exc)
    if extra:
        snap["event_extra"] = extra
    try:
        from elite_trader.admin_settings import _scenario_env_path, _parse_env_file

        ep = _scenario_env_path()
        if ep.is_file():
            snap["scenario_env"] = _parse_env_file(ep)
            snap["scenario_env_path"] = str(ep.name)
    except Exception as exc:
        snap["scenario_env_error"] = str(exc)
    iid = os.getenv("MEGA_INSTANCE_ID", os.getenv("BINANCE_ELITE_PORT", "")).strip()
    if iid in ("9006", "9007"):
        mega_dir = _ROOT / "data" / f"mega_{iid}"
        mega_meta: dict[str, Any] = {}
        for name in ("open_meta.json", "control_state.json"):
            fp = mega_dir / name
            if fp.is_file():
                try:
                    mega_meta[name.replace(".json", "")] = json.loads(fp.read_text(encoding="utf-8"))
                except Exception as exc:
                    mega_meta[name] = {"error": str(exc)}
        if mega_meta:
            snap["mega_meta"] = mega_meta
    return snap


def _build_restore_playbook(
    event_type: str,
    label: str,
    details: dict[str, Any],
    state: dict[str, Any],
) -> str:
    lines = [
        "## AI_RESTORE_PLAYBOOK",
        "",
        "Bu checkpoint'e dönmek için aşağıdaki adımları uygula. "
        "**9005 state DB, lessons ve evrim_persistent_learning.json silinmemeli** "
        "(DATA_PRESERVATION).",
        "",
    ]
    rt = state.get("runtime") or {}
    ps_file = state.get("panel_strategy_state") or {}
    if event_type in ("restart", "restart_boot"):
        lines.extend(
            [
                "### Restart durumu",
                "- Bot yeniden başlatıldı; aşağıdaki `panel_strategy_state` ve profiller geçerlidir.",
                "- Gerekirse: `./run_binance_elite_8300_9005.sh`",
                "",
            ]
        )
    if event_type == "motor_execution":
        old = details.get("old_mode", "?")
        new = details.get("new_mode", rt.get("execution_mode", "?"))
        lines.extend(
            [
                "### 1. Emir motoru",
                f"- `execution_mode`: `{new}` (önceki: `{old}`)",
                "```python",
                "from elite_trader.panel_strategy import set_execution_mode",
                f'set_execution_mode("{new}", note="restore from checkpoint")',
                "```",
                "",
            ]
        )
    if event_type == "view_mode":
        new = details.get("view_mode", rt.get("view_mode", "?"))
        lines.extend(
            [
                "### 1. Panel görünümü",
                f"- `view_mode`: `{new}`",
                "```python",
                "from elite_trader.panel_strategy import set_view_mode",
                f'set_view_mode("{new}")',
                "```",
                "",
            ]
        )
    if event_type in ("profile_patch", "profile_reset"):
        mid = details.get("mode_id", "evrim")
        patch = details.get("patch") or details.get("applied") or {}
        lines.extend(
            [
                f"### 1. Mod profili `{mid}`",
                "```python",
                "from elite_trader.mode_profiles import save_profile",
                f"save_profile({mid!r}, {json.dumps(patch, ensure_ascii=False)})",
                "```",
                "",
            ]
        )
    if event_type == "live_settings":
        patch = details.get("patch") or details.get("applied") or {}
        lines.extend(
            [
                "### 1. Ana Hat / live env patch",
                f"- Uygulanan alanlar: `{list(patch.keys())}`",
                "```json",
                json.dumps(patch, ensure_ascii=False, indent=2),
                "```",
                "",
            ]
        )
    if event_type == "evrim_config":
        lines.extend(
            [
                "### 1. Evrim config onayı",
                f"- suggestion_id: `{details.get('suggestion_id', '?')}`",
                "",
            ]
        )
    if ps_file:
        lines.extend(
            [
                "### 2. panel_strategy_state.json (tam)",
                "```json",
                json.dumps(ps_file, ensure_ascii=False, indent=2)[:12000],
                "```",
                "",
            ]
        )
    prof = state.get("mode_profiles")
    if prof and event_type.startswith("profile"):
        mid = details.get("mode_id", "evrim")
        modes = prof.get("modes") or prof
        block = modes.get(mid) if isinstance(modes, dict) else None
        if block:
            lines.extend(
                [
                    f"### 3. mode_profiles.json → `{mid}`",
                    "```json",
                    json.dumps(block, ensure_ascii=False, indent=2)[:8000],
                    "```",
                    "",
                ]
            )
    lines.extend(
        [
            "### Koruma — dokunma",
            "- `data/binance_elite_8300_9005_state.db`",
            "- `data/evrim_persistent_learning.json`",
            "- `data/deleted_archives/`",
            "",
        ]
    )
    return "\n".join(lines)


def write_checkpoint(
    event_type: str,
    *,
    label: str = "",
    name_parts: list[str] | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Yeni MD dosyası yazar; eskileri silmez.
    name_parts: dosya adına eklenecek slug parçaları (ayar adı vb.)
    """
    CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
    parts = [_slug(event_type, 24)]
    for p in name_parts or []:
        sp = _slug(p, 32)
        if sp and sp not in parts:
            parts.append(sp)
    slug = "_".join(parts)[:80]
    filename = f"{_stamp()}__{slug}.md"
    path = CHECKPOINT_DIR / filename

    details = dict(details or {})
    state = _collect_state_snapshot(details)
    title = label or event_type.replace("_", " ").title()

    body_lines = [
        f"# Checkpoint — {title}",
        "",
        "## CHECKPOINT_META",
        "",
        f"| Alan | Değer |",
        f"|------|-------|",
        f"| checkpoint_id | `{filename.replace('.md', '')}` |",
        f"| created_at | `{_now_iso()}` |",
        f"| event_type | `{event_type}` |",
        f"| label | {title} |",
        f"| project_root | `{_ROOT.name}` |",
        f"| md_path | `data/reports/checkpoints/{filename}` |",
        "",
    ]
    if details:
        body_lines.extend(["## EVENT_DETAILS", "", "```json"])
        body_lines.append(json.dumps(details, ensure_ascii=False, indent=2, default=str))
        body_lines.extend(["```", ""])

    body_lines.append(_build_restore_playbook(event_type, title, details, state))
    body_lines.extend(["## FULL_STATE_SNAPSHOT", "", "```json"])
    body_lines.append(json.dumps(state, ensure_ascii=False, indent=2, default=str)[:50000])
    body_lines.extend(["```", ""])

    md = "\n".join(body_lines)
    path.write_text(md, encoding="utf-8")

    entry = {
        "file": filename,
        "event_type": event_type,
        "label": title,
        "slug": slug,
        "created_at": _now_iso(),
        "bytes": path.stat().st_size,
        "details_preview": {
            k: details[k]
            for k in list(details.keys())[:8]
        },
    }
    idx = _load_index()
    idx.setdefault("checkpoints", []).append(entry)
    _save_index(idx)
    return {"ok": True, "file": filename, "path": str(path.relative_to(_ROOT)), "entry": entry}


def list_recent_checkpoints(limit: int = 3) -> list[dict[str, Any]]:
    idx = _load_index()
    cps = list(idx.get("checkpoints") or [])
    cps.reverse()
    out: list[dict[str, Any]] = []
    for row in cps[: max(1, min(limit, 20))]:
        f = row.get("file")
        if f and (CHECKPOINT_DIR / f).is_file():
            out.append(row)
    return out


def read_checkpoint_content(filename: str) -> str | None:
    safe = _safe_filename(filename)
    if not safe:
        return None
    return (CHECKPOINT_DIR / safe).read_text(encoding="utf-8")


def checkpoint_download_path(filename: str) -> Path | None:
    safe = _safe_filename(filename)
    if not safe:
        return None
    return CHECKPOINT_DIR / safe


def on_restart(*, source: str = "bot", note: str = "") -> dict[str, Any]:
    return write_checkpoint(
        "restart",
        label=f"Restart — {source}",
        name_parts=[source, note or "9005"],
        details={"source": source, "note": note},
    )


def on_restart_boot(*, pid: int | None = None) -> dict[str, Any]:
    return write_checkpoint(
        "restart_boot",
        label="Bot açılış (startup)",
        name_parts=["boot", "9005"],
        details={"pid": pid, "phase": "application_startup"},
    )


def on_motor_change(old: str, new: str, *, note: str = "") -> dict[str, Any]:
    return write_checkpoint(
        "motor_execution",
        label=f"Emir motoru {old} → {new}",
        name_parts=["motor", new, f"from_{old}"],
        details={"old_mode": old, "new_mode": new, "note": note},
    )


def on_view_change(old: str, new: str) -> dict[str, Any]:
    return write_checkpoint(
        "view_mode",
        label=f"Görünüm {old} → {new}",
        name_parts=["view", new],
        details={"old_view": old, "new_view": new, "view_mode": new},
    )


def on_profile_patch(mode_id: str, patch: dict[str, Any], *, source: str = "") -> dict[str, Any]:
    keys = "_".join(_slug(k, 12) for k in list(patch.keys())[:4])
    return write_checkpoint(
        "profile_patch",
        label=f"Profil {mode_id}: {', '.join(list(patch.keys())[:5])}",
        name_parts=["profile", mode_id, keys or "patch"],
        details={"mode_id": mode_id, "patch": patch, "source": source},
    )


def on_profile_reset(mode_id: str) -> dict[str, Any]:
    return write_checkpoint(
        "profile_reset",
        label=f"Profil sıfır — {mode_id}",
        name_parts=["profile_reset", mode_id],
        details={"mode_id": mode_id},
    )


def on_live_settings(patch: dict[str, Any], *, source: str = "") -> dict[str, Any]:
    keys = "_".join(_slug(k, 14) for k in list(patch.keys())[:3])
    return write_checkpoint(
        "live_settings",
        label=f"Live ayar: {', '.join(list(patch.keys())[:4])}",
        name_parts=["live", keys or "settings"],
        details={"patch": patch, "source": source},
    )


def on_evrim_config_change(suggestion_id: str, result: dict[str, Any]) -> dict[str, Any]:
    return write_checkpoint(
        "evrim_config",
        label=f"Evrim config — {suggestion_id[:24]}",
        name_parts=["evrim_config", suggestion_id[:20]],
        details={"suggestion_id": suggestion_id, "result": result},
    )


def on_admin_settings(patch: dict[str, Any], *, source: str = "") -> dict[str, Any]:
    keys = "_".join(_slug(k, 12) for k in list(patch.keys())[:4])
    return write_checkpoint(
        "admin_settings",
        label=f"Admin env: {', '.join(list(patch.keys())[:5])}",
        name_parts=["admin", keys or "settings"],
        details={"patch": patch, "applied": patch, "source": source},
    )


def parse_checkpoint_snapshot(filename: str) -> dict[str, Any] | None:
    """Extract FULL_STATE_SNAPSHOT JSON from checkpoint markdown."""
    content = read_checkpoint_content(filename)
    if not content:
        return None
    marker = "## FULL_STATE_SNAPSHOT"
    idx = content.find(marker)
    if idx < 0:
        return None
    rest = content[idx + len(marker) :]
    start = rest.find("```json")
    if start < 0:
        return None
    start = rest.find("\n", start) + 1
    end = rest.find("```", start)
    if end < 0:
        return None
    blob = rest[start:end].strip()
    try:
        return json.loads(blob)
    except Exception:
        return None


def rollback_preview(filename: str, scopes: list[str] | None = None) -> dict[str, Any]:
    safe = _safe_filename(filename)
    if not safe:
        return {"ok": False, "error": "invalid filename"}
    snap = parse_checkpoint_snapshot(safe)
    if not snap:
        return {"ok": False, "error": "snapshot not found"}
    scopes = scopes or ["panel_strategy_state", "mode_profiles"]
    summary: dict[str, Any] = {"filename": safe, "scopes": scopes, "items": []}
    if "scenario_env" in scopes:
        env = snap.get("scenario_env") or {}
        summary["items"].append({"scope": "scenario_env", "keys": list(env.keys())[:20]})
    if "panel_strategy_state" in scopes and snap.get("panel_strategy_state"):
        summary["items"].append({"scope": "panel_strategy_state", "keys": list(snap["panel_strategy_state"].keys())})
    if "mode_profiles" in scopes and snap.get("mode_profiles"):
        prof = snap["mode_profiles"]
        modes = prof.get("modes") if isinstance(prof, dict) else prof
        summary["items"].append({"scope": "mode_profiles", "modes": list(modes.keys()) if isinstance(modes, dict) else []})
    if "mega_meta" in scopes:
        summary["items"].append({"scope": "mega_meta", "note": "open_meta + control_state if present in snapshot"})
    if "lab_data" in scopes:
        summary["items"].append({"scope": "lab_data", "note": "optional lab_9007 restore — default off"})
    return {"ok": True, "preview": summary, "collected_at": snap.get("collected_at")}


def rollback_checkpoint(
    filename: str,
    *,
    scopes: list[str] | None = None,
    reason: str = "",
    confirm: bool = False,
) -> dict[str, Any]:
    if not confirm:
        return {"ok": False, "error": "confirm required"}
    safe = _safe_filename(filename)
    if not safe:
        return {"ok": False, "error": "invalid filename"}
    snap = parse_checkpoint_snapshot(safe)
    if not snap:
        return {"ok": False, "error": "snapshot not found"}
    scopes = scopes or ["panel_strategy_state", "mode_profiles"]
    write_checkpoint(
        "rollback_pre",
        label=f"Pre-rollback — {safe[:40]}",
        name_parts=["rollback_pre", safe.replace(".md", "")[:24]],
        details={"target": safe, "scopes": scopes, "reason": reason},
    )
    restored: list[str] = []
    errors: list[str] = []

    if "scenario_env" in scopes:
        env = snap.get("scenario_env") or {}
        if env:
            try:
                from elite_trader.admin_settings import patch_settings

                patch_settings({k: str(v) for k, v in env.items()}, source=f"rollback:{safe}")
                restored.append("scenario_env")
            except Exception as exc:
                errors.append(f"scenario_env: {exc}")

    if "panel_strategy_state" in scopes:
        ps = snap.get("panel_strategy_state")
        if ps:
            path = _ROOT / "data" / "panel_strategy_state.json"
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(ps, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                restored.append("panel_strategy_state")
            except Exception as exc:
                errors.append(f"panel_strategy_state: {exc}")

    if "mode_profiles" in scopes:
        prof = snap.get("mode_profiles")
        if prof:
            path = _ROOT / "data" / "mode_profiles.json"
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(prof, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                restored.append("mode_profiles")
            except Exception as exc:
                errors.append(f"mode_profiles: {exc}")

    if "mega_meta" in scopes:
        meta = snap.get("mega_meta") or {}
        iid = os.getenv("MEGA_INSTANCE_ID", os.getenv("BINANCE_ELITE_PORT", "9007")).strip()
        mega_dir = _ROOT / "data" / f"mega_{iid}"
        try:
            mega_dir.mkdir(parents=True, exist_ok=True)
            for name in ("open_meta.json", "control_state.json"):
                if name in meta:
                    (mega_dir / name).write_text(
                        json.dumps(meta[name], ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8",
                    )
            restored.append("mega_meta")
        except Exception as exc:
            errors.append(f"mega_meta: {exc}")

    write_checkpoint(
        "rollback",
        label=f"Rollback — {safe[:36]}",
        name_parts=["rollback", safe.replace(".md", "")[:20]],
        details={"target": safe, "scopes": scopes, "reason": reason, "restored": restored},
    )
    return {"ok": not errors, "restored": restored, "errors": errors, "target": safe}
