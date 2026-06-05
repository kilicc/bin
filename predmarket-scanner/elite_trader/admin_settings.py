"""Admin settings schema, values, impact graph for 9007 desk."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from elite_trader.settings_registry import (
    PARALLEL_FIELDS,
    apply_live_settings,
    get_profile,
    live_settings_bundle,
    parallel_profiles,
    preview_live_patch,
    save_profile,
)

_ROOT = Path(__file__).resolve().parent.parent
_SCHEMA_PATH = _ROOT / "data" / "admin_settings_schema.json"

_ADMIN_ENV_PREFIXES = ("MEGA_", "ELITE_", "BERSERK2_", "BINANCE_", "LAB_")

_IMPACT_EDGES: list[tuple[str, str, str]] = [
    ("ELITE_MIN_STAKE_USD", "deployable_slots", "Yüksek min stake → daha az slot"),
    ("ELITE_MAX_OPEN", "open_capacity", "Max açık → eşzamanlı pozisyon"),
    ("ELITE_MIN_STAKE_USD", "ELITE_MAX_OPEN", "Min stake max açık ile birlikte"),
    ("ELITE_MAX_STAKE_USD", "ELITE_MIN_STAKE_USD", "Max stake min stake üstü olmalı"),
    ("MEGA_LIVE_ORDERS", "exchange_orders", "Canlı emir — restart gerekir"),
    ("MEGA_LIVE_ORDERS", "BINANCE_API_KEY", "Canlı emir API anahtarı gerektirir"),
    ("MEGA_SIM_ENABLED", "sim_book", "Paper sim kitap"),
    ("BINANCE_LEVERAGE_MAX", "margin_usage", "Kaldıraç üst limiti"),
    ("ELITE_SCAN_INTERVAL_SEC", "scan_rate", "Tarama sıklığı"),
    ("MEGA_EXCHANGE_DUAL_TP", "MEGA_LIVE_ORDERS", "Dual TP canlı emir gerektirir"),
]

_FIELD_DEPENDS: dict[str, list[str]] = {
    "ELITE_MIN_STAKE_USD": ["ELITE_MAX_OPEN"],
    "ELITE_MAX_STAKE_USD": ["ELITE_MAX_OPEN", "ELITE_MIN_STAKE_USD"],
    "MEGA_LIVE_ORDERS": ["BINANCE_API_KEY", "BINANCE_API_SECRET"],
    "MEGA_EXCHANGE_DUAL_TP": ["MEGA_LIVE_ORDERS"],
    "LAB_LLM_MODEL": ["OPENAI_API_KEY", "GCP_PROJECT"],
    "LAB_LLM_PROVIDER": ["GCP_PROJECT", "OPENAI_API_KEY"],
    "LAB_VISION_MODEL": ["GCP_PROJECT", "OPENAI_API_KEY"],
}


def _depends_on(key: str) -> list[str]:
    deps = set(_FIELD_DEPENDS.get(key, []))
    for src, tgt, _ in _IMPACT_EDGES:
        if src == key:
            if tgt.isupper() and "_" in tgt:
                deps.add(tgt)
        if tgt == key and src.isupper() and "_" in src:
            deps.add(src)
    return sorted(deps)


def _scenario_env_path() -> Path:
    custom = os.getenv("BINANCE_ELITE_SCENARIO", "").strip()
    if custom:
        p = Path(custom)
        return p if p.is_absolute() else (_ROOT / p)
    iid = os.getenv("MEGA_INSTANCE_ID", os.getenv("BINANCE_ELITE_PORT", "")).strip()
    if iid == "9007":
        return _ROOT / "scenarios" / "binance_elite_mega_9007.env"
    return _ROOT / "scenarios" / "binance_elite_mega_9006.env"


def _parse_env_file(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        k, _, v = line.partition("=")
        out[k.strip()] = v.strip()
    return out


def _infer_type(val: str) -> str:
    vl = val.lower()
    if vl in ("0", "1", "true", "false", "yes", "no"):
        return "bool"
    if re.fullmatch(r"-?\d+", val):
        return "int"
    if re.fullmatch(r"-?\d+\.\d+", val):
        return "float"
    return "string"


def _field_meta(key: str, val: str) -> dict[str, Any]:
    t = _infer_type(val)
    group = "general"
    if key.startswith("MEGA_"):
        group = "mega"
    elif key.startswith("ELITE_"):
        group = "elite"
    elif key.startswith("BERSERK2_"):
        group = "berserk2"
    elif key.startswith("BINANCE_"):
        group = "binance"
    elif key.startswith("LAB_"):
        group = "lab"
    requires_restart = key in (
        "MEGA_LIVE_ORDERS",
        "MEGA_SIM_ENABLED",
        "MEGA_INSTANCE_ID",
        "BINANCE_ELITE_PORT",
        "ELITE_ENABLED_MODES",
    )
    return {
        "key": key,
        "type": t,
        "group": group,
        "label": key.replace("_", " ").title(),
        "requires_restart": requires_restart,
        "depends_on": _depends_on(key),
        "scope": "env",
        "default": val,
    }


def _profile_field_meta(field: dict[str, Any], mode_id: str) -> dict[str, Any]:
    return {
        "key": field["key"],
        "type": field.get("type", "string"),
        "group": field.get("group", "profile"),
        "label": field.get("label", field["key"]),
        "min": field.get("min"),
        "max": field.get("max"),
        "step": field.get("step"),
        "options": field.get("options"),
        "hint": field.get("hint"),
        "requires_restart": False,
        "depends_on": [],
        "scope": "profile",
        "profile_mode_id": mode_id,
    }


def build_schema() -> dict[str, Any]:
    env = _parse_env_file(_scenario_env_path())
    fields: list[dict[str, Any]] = []
    for k, v in sorted(env.items()):
        if not k.startswith(_ADMIN_ENV_PREFIXES):
            continue
        fields.append(_field_meta(k, v))
    for mode_id in ("mega", "evrim"):
        prof = get_profile(mode_id) or {}
        for pf in PARALLEL_FIELDS:
            meta = _profile_field_meta(pf, mode_id)
            meta["default"] = prof.get(pf["key"])
            fields.append(meta)
    groups = sorted({f["group"] for f in fields})
    payload = {"version": 2, "fields": fields, "groups": groups}
    _SCHEMA_PATH.parent.mkdir(parents=True, exist_ok=True)
    _SCHEMA_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def get_schema() -> dict[str, Any]:
    if _SCHEMA_PATH.is_file():
        try:
            data = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
            if int(data.get("version") or 0) >= 2:
                return data
        except Exception:
            pass
    return build_schema()


def get_values() -> dict[str, Any]:
    env = _parse_env_file(_scenario_env_path())
    live = {}
    try:
        live = live_settings_bundle()
    except Exception:
        pass
    filtered = {k: v for k, v in env.items() if k.startswith(_ADMIN_ENV_PREFIXES)}
    runtime = {k: os.getenv(k, v) for k, v in filtered.items()}
    profiles = {}
    for mode_id in ("mega", "evrim"):
        profiles[mode_id] = get_profile(mode_id) or {}
    return {
        "scenario_env": filtered,
        "runtime_env": runtime,
        "live_bundle": live,
        "profiles": profiles,
        "scenario_path": str(_scenario_env_path().name),
    }


def get_impact(key: str | None = None) -> dict[str, Any]:
    nodes: list[str] = []
    edges = []
    depends_chain: list[str] = []
    if key:
        depends_chain = _depends_on(key)
        nodes.extend(depends_chain)
    for src, tgt, note in _IMPACT_EDGES:
        if key and src != key and tgt != key:
            continue
        nodes.extend([src, tgt])
        edges.append({"from": src, "to": tgt, "note": note})
    if key:
        nodes.append(key)
    return {
        "key": key,
        "nodes": sorted(set(nodes)),
        "edges": edges,
        "depends_on": depends_chain,
    }


def _diff_dict(before: dict[str, Any], after: dict[str, Any]) -> list[dict[str, Any]]:
    keys = sorted(set(before) | set(after))
    out: list[dict[str, Any]] = []
    for k in keys:
        b, a = before.get(k), after.get(k)
        if str(b) != str(a):
            out.append({"key": k, "before": b, "after": a})
    return out


def preview_settings(patch: dict[str, Any]) -> dict[str, Any]:
    schema = get_schema()
    field_map = {f["key"]: f for f in schema.get("fields") or [] if f.get("scope") == "env"}
    values = get_values()
    before = dict(values.get("runtime_env") or {})
    after = dict(before)
    errors: list[str] = []
    restart_keys: list[str] = []
    for k, v in patch.items():
        if k not in field_map:
            errors.append(f"unknown: {k}")
            continue
        after[k] = v
        if field_map[k].get("requires_restart"):
            restart_keys.append(k)
    live_patch: dict[str, Any] = {}
    _live_map = {
        "ELITE_MIN_STAKE_USD": "ELITE_MIN_STAKE_USD",
        "ELITE_MAX_STAKE_USD": "ELITE_MAX_STAKE_USD",
        "ELITE_MAX_OPEN": "ELITE_MAX_OPEN",
    }
    for ek, lk in _live_map.items():
        if ek in patch:
            live_patch[lk] = patch[ek]
    live_preview = preview_live_patch(live_patch) if live_patch else None
    return {
        "ok": not errors,
        "errors": errors,
        "diff": _diff_dict(before, after),
        "requires_restart": bool(restart_keys),
        "restart_keys": restart_keys,
        "live_preview": live_preview,
    }


def preview_profile(mode_id: str, patch: dict[str, Any]) -> dict[str, Any]:
    before = dict(get_profile(mode_id) or {})
    after = dict(before)
    after.update(patch)
    field_keys = {f["key"] for f in PARALLEL_FIELDS}
    errors = [f"unknown: {k}" for k in patch if k not in field_keys]
    return {
        "ok": not errors,
        "errors": errors,
        "mode_id": mode_id,
        "diff": _diff_dict(before, after),
    }


def list_profiles() -> dict[str, Any]:
    return {"profiles": parallel_profiles(), "modes": ["mega", "evrim"]}


def get_profile_values(mode_id: str) -> dict[str, Any]:
    return {"mode_id": mode_id, "profile": get_profile(mode_id) or {}}


def patch_profile(mode_id: str, patch: dict[str, Any], *, source: str = "admin") -> dict[str, Any]:
    prev = preview_profile(mode_id, patch)
    if not prev.get("ok"):
        return {"ok": False, "errors": prev.get("errors")}
    cleaned = {k: v for k, v in patch.items() if k in {f["key"] for f in PARALLEL_FIELDS}}
    profile = save_profile(mode_id, cleaned)
    try:
        from elite_trader.system_checkpoint_md import on_profile_patch

        on_profile_patch(mode_id, cleaned, source=source)
    except Exception:
        pass
    return {"ok": True, "mode_id": mode_id, "profile": profile, "applied": cleaned}


def patch_settings(patch: dict[str, Any], *, source: str = "admin") -> dict[str, Any]:
    """Validate and apply env patch to scenario file + live settings where mapped."""
    schema = get_schema()
    field_map = {f["key"]: f for f in schema.get("fields") or [] if f.get("scope") == "env"}
    errors: list[str] = []
    env_patch: dict[str, str] = {}
    live_patch: dict[str, Any] = {}
    for k, v in patch.items():
        meta = field_map.get(k)
        if not meta:
            errors.append(f"unknown: {k}")
            continue
        t = meta.get("type")
        try:
            if t == "bool":
                env_patch[k] = "1" if str(v).lower() in ("1", "true", "yes") else "0"
            elif t == "int":
                env_patch[k] = str(int(float(v)))
            elif t == "float":
                env_patch[k] = str(float(v))
            else:
                env_patch[k] = str(v)
        except (TypeError, ValueError):
            errors.append(f"invalid {k}")
    if errors:
        return {"ok": False, "errors": errors}
    path = _scenario_env_path()
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    new_lines: list[str] = []
    seen: set[str] = set()
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in env_patch:
                new_lines.append(f"{key}={env_patch[key]}")
                seen.add(key)
                continue
        new_lines.append(line)
    for k, v in env_patch.items():
        if k not in seen:
            new_lines.append(f"{k}={v}")
    path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    for k, v in env_patch.items():
        os.environ[k] = v
    _live_map = {
        "ELITE_MIN_STAKE_USD": "ELITE_MIN_STAKE_USD",
        "ELITE_MAX_STAKE_USD": "ELITE_MAX_STAKE_USD",
        "ELITE_MAX_OPEN": "ELITE_MAX_OPEN",
    }
    for ek, lk in _live_map.items():
        if ek in env_patch:
            try:
                live_patch[lk] = float(env_patch[ek]) if "STAKE" in ek or ek.endswith("_OPEN") else env_patch[ek]
            except ValueError:
                live_patch[lk] = env_patch[ek]
    live_result = None
    if live_patch:
        prev = preview_live_patch(live_patch)
        if prev.get("ok"):
            live_result = apply_live_settings(live_patch)
    try:
        from elite_trader.mega_control import audit_log

        audit_log("admin_settings_patch", keys=list(env_patch.keys()))
    except Exception:
        pass
    try:
        from elite_trader.system_checkpoint_md import on_admin_settings

        on_admin_settings(env_patch, source=source)
    except Exception:
        pass
    restart_needed = any(field_map.get(k, {}).get("requires_restart") for k in env_patch)
    return {
        "ok": True,
        "applied": env_patch,
        "live_result": live_result,
        "requires_restart": restart_needed,
    }
