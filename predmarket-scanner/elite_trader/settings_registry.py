"""Ayar şeması — Ana Hat senaryo .env (onaylı); paralel modlar JSON."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from elite_trader.mode_profiles import (
    PARALLEL_IDS,
    get_profile,
    parallel_profiles,
    reset_profile,
    save_profile,
)

_ROOT = Path(__file__).resolve().parent.parent
_LIVE_SCENARIO = _ROOT / "scenarios" / "binance_elite_8300_9005.env"

# Paralel mod alanları — Ana Hat ile aynı ölçek (mutlak değerler, profil JSON)
PARALLEL_FIELDS: list[dict[str, Any]] = [
    {"key": "min_edge", "type": "float", "min": 0.02, "max": 0.99, "step": 0.001,
     "label": "Min edge", "group": "entry"},
    {"key": "min_formula_score", "type": "float", "min": 0.35, "max": 0.99, "step": 0.01,
     "label": "Min formül skoru", "group": "entry"},
    {"key": "market_cooldown_min", "type": "int", "min": 0, "max": 120, "step": 1,
     "label": "Sembol cooldown (dk)", "group": "entry"},
    {"key": "tp_stake_pct", "type": "float", "min": 0.003, "max": 0.05, "step": 0.0001,
     "label": "TP stake %", "group": "exit",
     "hint": "0.0055 = %0.55"},
    {"key": "sl_stake_pct", "type": "float", "min": 0.001, "max": 0.02, "step": 0.0001,
     "label": "SL stake %", "group": "exit", "hint": "0.003 = %0.30"},
    {"key": "tp_trigger_frac", "type": "float", "min": 0.5, "max": 1.1, "step": 0.01,
     "label": "TP trigger", "group": "exit"},
    {"key": "spike_enabled", "type": "bool", "label": "Spike açık", "group": "exit"},
    {"key": "spike_min_age_sec", "type": "float", "min": 5, "max": 180, "step": 5,
     "label": "Spike min sn", "group": "exit"},
    {"key": "spike_fee_mult", "type": "float", "min": 1.0, "max": 2.0, "step": 0.01,
     "label": "Spike fee mult", "group": "exit"},
    {"key": "spike_max_tp_frac", "type": "float", "min": 0.3, "max": 1.0, "step": 0.02,
     "label": "Spike max TP frac", "group": "exit"},
    {"key": "stale_enabled", "type": "bool", "label": "Stale açık", "group": "exit"},
    {"key": "stale_min_age_min", "type": "float", "min": 0.25, "max": 60, "step": 0.25,
     "label": "Stale min dk", "group": "exit"},
    {"key": "stale_mode", "type": "enum", "options": ["flat_release", "recover"],
     "label": "Stale mod", "group": "exit"},
    {"key": "starting_balance", "type": "float", "min": 100, "max": 100000, "step": 100,
     "label": "Başlangıç bakiye (oturum)", "group": "capital"},
    {"key": "min_stake_usd", "type": "float", "min": 50, "max": 5000, "step": 10,
     "label": "Min stake USD", "group": "capital"},
    {"key": "active_capital_pct", "type": "float", "min": 0.1, "max": 1.0, "step": 0.05,
     "label": "Aktif sermaye %", "group": "capital"},
    {"key": "max_open", "type": "int", "min": 1, "max": 30, "step": 1,
     "label": "Max açık", "group": "capital"},
    {"key": "scan_interval_sec", "type": "float", "min": 2, "max": 60, "step": 1,
     "label": "Tarama sn", "group": "scan"},
    {"key": "position_check_sec", "type": "float", "min": 0.25, "max": 10, "step": 0.25,
     "label": "Pozisyon kontrol sn", "group": "scan"},
    {"key": "trade_top_n", "type": "int", "min": 10, "max": 200, "step": 5,
     "label": "Emir çekirdek N", "group": "scan"},
    {"key": "sl_em_veto_count", "type": "int", "min": 0, "max": 10, "step": 1,
     "label": "SL-EM veto eşiği", "group": "risk"},
    {"key": "sl_em_cooldown_min", "type": "int", "min": 0, "max": 240, "step": 5,
     "label": "SL-EM cooldown dk", "group": "risk"},
    {"key": "min_hold_before_sl_sec", "type": "int", "min": 0, "max": 300, "step": 5,
     "label": "Min hold SL öncesi sn", "group": "risk"},
    {"key": "sl_emergency_mult", "type": "float", "min": 0.5, "max": 3.0, "step": 0.1,
     "label": "SL emergency mult", "group": "risk"},
    {"key": "entry_min_strength", "type": "enum", "options": ["Weak", "Medium", "Strong"],
     "label": "Min sinyal gücü", "group": "entry"},
    {"key": "entry_skip_cautious", "type": "bool",
     "label": "Temkinli girişleri atla", "group": "entry"},
    {"key": "entry_block_weak", "type": "bool", "label": "Weak sinyal at", "group": "entry"},
    {"key": "sentinel_min_quality_score", "type": "float", "min": 45, "max": 95, "step": 1,
     "label": "Sentinel min kalite skoru", "group": "sentinel"},
    {"key": "sentinel_chop_min_quality_score", "type": "float", "min": 55, "max": 95, "step": 1,
     "label": "Sentinel chop min kalite", "group": "sentinel"},
    {"key": "sentinel_allow_medium_if_quality", "type": "bool",
     "label": "Medium + kalite ile giriş", "group": "sentinel"},
    {"key": "sentinel_news_risk_mode", "type": "enum", "options": ["risk_off", "observe"],
     "label": "Sentinel haber riski", "group": "sentinel"},
    {"key": "sentinel_trend_misalignment_mode", "type": "enum", "options": ["veto", "observe"],
     "label": "Sentinel trend uyumsuzluğu", "group": "sentinel"},
    {"key": "medium_stake_multiplier", "type": "float", "min": 0.2, "max": 1.0, "step": 0.05,
     "label": "Medium stake çarpanı", "group": "sentinel"},
    {"key": "strong_stake_multiplier", "type": "float", "min": 0.5, "max": 1.5, "step": 0.05,
     "label": "Strong stake çarpanı", "group": "sentinel"},
    {"key": "max_spread_pct", "type": "float", "min": 0.04, "max": 0.25, "step": 0.01,
     "label": "Max spread %", "group": "sentinel"},
    {"key": "soft_spread_start_pct", "type": "float", "min": 0.02, "max": 0.15, "step": 0.01,
     "label": "Soft spread başlangıç %", "group": "sentinel"},
    {"key": "spread_policy", "type": "enum", "options": ["sentinel_strict", "strict", "normal"],
     "label": "Spread policy", "group": "sentinel"},
    {"key": "description", "type": "text", "label": "Açıklama", "group": "meta"},
    {"key": "evrim_auto_tune", "type": "bool", "label": "Evrim otomatik ayar", "group": "evrim"},
    {"key": "evrim_daily_mult", "type": "float", "min": 1.5, "max": 3.0, "step": 0.1,
     "label": "Günlük hedef çarpan (2×)", "group": "evrim"},
    {"key": "evrim_hourly_target_pct", "type": "float", "min": 1.0, "max": 12.0, "step": 0.5,
     "label": "Saatlik PnL velocity % hedef", "group": "evrim"},
    {"key": "evrim_vol_mult", "type": "float", "min": 1.2, "max": 3.0, "step": 0.05,
     "label": "Volume çarpanı (× avg)", "group": "evrim"},
    {"key": "evrim_atr_min_pct", "type": "float", "min": 0.03, "max": 0.2, "step": 0.005,
     "label": "Min ATR %", "group": "evrim"},
    {"key": "evrim_spread_tp_frac", "type": "float", "min": 0.08, "max": 0.35, "step": 0.01,
     "label": "Spread / TP max oran", "group": "evrim"},
    {"key": "evrim_loss_ban_min", "type": "int", "min": 5, "max": 60, "step": 5,
     "label": "2×SL ban (dk)", "group": "evrim"},
]

# Canlı Ana Hat — panelden yazılabilir (whitelist)
LIVE_EDITABLE_KEYS = frozenset({
    "ELITE_MIN_EDGE", "ELITE_MIN_FORMULA_SCORE", "ELITE_MARKET_COOLDOWN_MIN",
    "ELITE_TP_STAKE_PCT", "ELITE_SL_STAKE_PCT", "ELITE_TP_TRIGGER_FRAC",
    "ELITE_SPIKE_QUICK_TP_ENABLED", "ELITE_SPIKE_QUICK_TP_MIN_AGE_SEC",
    "ELITE_SPIKE_QUICK_TP_FEE_MULT", "ELITE_SPIKE_QUICK_TP_MAX_FRAC",
    "ELITE_STALE_TP_ENABLED", "ELITE_STALE_TP_MIN_AGE_MIN", "ELITE_STALE_MODE",
    "STARTING_BALANCE", "ELITE_MIN_STAKE_USD", "ELITE_ACTIVE_CAPITAL_PCT", "ELITE_MAX_OPEN",
    "ELITE_SCAN_INTERVAL_SEC", "ELITE_POSITION_CHECK_SEC", "BINANCE_TRADE_TOP_N",
    "ELITE_SL_EM_VETO_COUNT", "ELITE_SL_EM_COOLDOWN_MIN", "ELITE_MIN_HOLD_BEFORE_SL_SEC",
    "ELITE_SL_EMERGENCY_MULT",
    "ELITE_FEE_RATE_PER_SIDE", "ELITE_TP_FEE_COVER_MULT", "ELITE_ENTRY_REQUIRE_NET_TP",
    "ELITE_ENTRY_MIN_NET_USD", "ELITE_TP_NET_AFTER_FEE", "ELITE_DAILY_TARGET_MULT",
})

LIVE_KEY_META: dict[str, dict[str, Any]] = {
    "ELITE_MIN_EDGE": {"type": "float", "min": 0.02, "max": 0.99, "step": 0.001, "label": "Min edge", "group": "entry"},
    "ELITE_MIN_FORMULA_SCORE": {"type": "float", "min": 0.35, "max": 0.99, "step": 0.01, "label": "Min formül skoru", "group": "entry"},
    "ELITE_MARKET_COOLDOWN_MIN": {"type": "int", "min": 0, "max": 120, "step": 1, "label": "Sembol cooldown (dk)", "group": "entry"},
    "ELITE_TP_STAKE_PCT": {"type": "float", "min": 0.003, "max": 0.05, "step": 0.0001, "label": "TP stake % (0.014=1.4%)", "group": "exit"},
    "ELITE_SL_STAKE_PCT": {"type": "float", "min": 0.001, "max": 0.02, "step": 0.0001, "label": "SL stake % (0.0055=0.55%)", "group": "exit"},
    "ELITE_TP_TRIGGER_FRAC": {"type": "float", "min": 0.5, "max": 1.1, "step": 0.01, "label": "TP trigger", "group": "exit"},
    "ELITE_SPIKE_QUICK_TP_ENABLED": {"type": "bool", "label": "Spike açık", "group": "exit"},
    "ELITE_SPIKE_QUICK_TP_MIN_AGE_SEC": {"type": "float", "min": 5, "max": 180, "step": 5, "label": "Spike min sn", "group": "exit"},
    "ELITE_SPIKE_QUICK_TP_FEE_MULT": {"type": "float", "min": 1.0, "max": 2.0, "step": 0.01, "label": "Spike fee mult", "group": "exit"},
    "ELITE_SPIKE_QUICK_TP_MAX_FRAC": {"type": "float", "min": 0.3, "max": 1.0, "step": 0.02, "label": "Spike max TP frac", "group": "exit"},
    "ELITE_STALE_TP_ENABLED": {"type": "bool", "label": "Stale açık", "group": "exit"},
    "ELITE_STALE_TP_MIN_AGE_MIN": {"type": "float", "min": 0.25, "max": 60, "step": 0.25, "label": "Stale min dk", "group": "exit"},
    "ELITE_STALE_MODE": {"type": "enum", "options": ["flat_release", "recover"], "label": "Stale mod", "group": "exit"},
    "STARTING_BALANCE": {"type": "float", "min": 100, "max": 100000, "step": 100, "label": "Başlangıç bakiye (oturum)", "group": "capital"},
    "ELITE_MIN_STAKE_USD": {"type": "float", "min": 50, "max": 5000, "step": 10, "label": "Min stake USD", "group": "capital"},
    "ELITE_ACTIVE_CAPITAL_PCT": {"type": "float", "min": 0.1, "max": 1.0, "step": 0.05, "label": "Aktif sermaye %", "group": "capital"},
    "ELITE_MAX_OPEN": {"type": "int", "min": 1, "max": 30, "step": 1, "label": "Max açık", "group": "capital"},
    "ELITE_SCAN_INTERVAL_SEC": {"type": "float", "min": 2, "max": 60, "step": 1, "label": "Tarama sn", "group": "scan"},
    "ELITE_POSITION_CHECK_SEC": {"type": "float", "min": 0.25, "max": 10, "step": 0.25, "label": "Pozisyon kontrol sn", "group": "scan"},
    "BINANCE_TRADE_TOP_N": {"type": "int", "min": 10, "max": 200, "step": 5, "label": "Emir çekirdek N", "group": "scan"},
    "ELITE_SL_EM_VETO_COUNT": {"type": "int", "min": 1, "max": 10, "step": 1, "label": "SL-EM veto eşiği", "group": "risk"},
    "ELITE_SL_EM_COOLDOWN_MIN": {"type": "int", "min": 0, "max": 240, "step": 5, "label": "SL-EM cooldown dk", "group": "risk"},
    "ELITE_MIN_HOLD_BEFORE_SL_SEC": {"type": "int", "min": 0, "max": 300, "step": 5, "label": "Min hold SL öncesi sn", "group": "risk"},
    "ELITE_SL_EMERGENCY_MULT": {"type": "float", "min": 0.5, "max": 3.0, "step": 0.1, "label": "SL emergency mult", "group": "risk"},
}

LIVE_ENV_GROUPS: list[dict[str, Any]] = [
    {"group": "entry", "label": "Giriş filtreleri", "keys": [
        ("ELITE_MIN_EDGE", "Min edge"),
        ("ELITE_MIN_FORMULA_SCORE", "Min formül skoru"),
        ("ELITE_MARKET_COOLDOWN_MIN", "Sembol cooldown (dk)"),
    ]},
    {"group": "exit", "label": "Çıkış (Ana Hat motor)", "keys": [
        ("ELITE_TP_STAKE_PCT", "TP stake %"),
        ("ELITE_SL_STAKE_PCT", "SL stake %"),
        ("ELITE_TP_TRIGGER_FRAC", "TP trigger"),
        ("ELITE_SPIKE_QUICK_TP_ENABLED", "Spike"),
        ("ELITE_SPIKE_QUICK_TP_MIN_AGE_SEC", "Spike min sn"),
        ("ELITE_STALE_TP_ENABLED", "Stale"),
        ("ELITE_STALE_TP_MIN_AGE_MIN", "Stale min dk"),
    ]},
    {"group": "capital", "label": "Sermaye", "keys": [
        ("STARTING_BALANCE", "Başlangıç"),
        ("ELITE_MIN_STAKE_USD", "Min stake"),
        ("ELITE_ACTIVE_CAPITAL_PCT", "Aktif sermaye %"),
        ("ELITE_MAX_OPEN", "Max açık"),
    ]},
    {"group": "scan", "label": "Tarama", "keys": [
        ("ELITE_SCAN_INTERVAL_SEC", "Tarama sn"),
        ("ELITE_POSITION_CHECK_SEC", "Pozisyon kontrol sn"),
        ("BINANCE_TRADE_TOP_N", "Emir çekirdek N"),
    ]},
    {"group": "risk", "label": "Risk / SL-EM", "keys": [
        ("ELITE_SL_EM_VETO_COUNT", "Veto eşiği"),
        ("ELITE_SL_EM_COOLDOWN_MIN", "Cooldown dk"),
        ("ELITE_MIN_HOLD_BEFORE_SL_SEC", "Min hold SL öncesi sn"),
    ]},
]


def _coerce(field: dict[str, Any], value: Any) -> Any:
    t = field.get("type")
    if t == "bool":
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in ("1", "true", "yes", "on")
    if t == "int":
        v = int(float(value))
        return max(int(field.get("min", 0)), min(int(field.get("max", 999)), v))
    if t == "float":
        v = float(value)
        return max(float(field.get("min", 0)), min(float(field.get("max", 1e6)), v))
    if t == "enum":
        opts = field.get("options") or []
        s = str(value).strip()
        return s if s in opts else opts[0]
    return str(value)[:500]


def _scenario_env_map() -> dict[str, str]:
    out: dict[str, str] = {}
    if not _LIVE_SCENARIO.is_file():
        return out
    for line in _LIVE_SCENARIO.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if "=" in s and not s.startswith("#"):
            k, _, v = s.partition("=")
            out[k.strip()] = v.strip()
    return out


def live_settings_bundle() -> dict[str, Any]:
    """Ana Hat — dosyadan okunur, düzenlenebilir alanlar."""
    cur = _scenario_env_map()
    fields = [
        {"key": k, **{kk: vv for kk, vv in meta.items() if kk != "key"}}
        for k, meta in LIVE_KEY_META.items()
    ]
    values = {k: cur.get(k, os.getenv(k, "")) for k in LIVE_KEY_META}
    return {
        "scope": "live",
        "readonly": False,
        "scenario_file": str(_LIVE_SCENARIO.name),
        "scenario_path": str(_LIVE_SCENARIO),
        "note": (
            "Ana Hat → scenarios/binance_elite_8300_9005.env. "
            "Kaydet + Restart ile bot yeni ayarlarla açılır. Açık pozisyonlar borsada kalır."
        ),
        "fields": fields,
        "values": values,
        "editable_keys": sorted(LIVE_EDITABLE_KEYS),
    }


def live_settings_readonly() -> dict[str, Any]:
    return live_settings_bundle()


def parallel_settings_bundle(mode_id: str | None = None) -> dict[str, Any]:
    profiles = parallel_profiles()
    fields = PARALLEL_FIELDS
    modes_out = []
    for mid in PARALLEL_IDS:
        p = profiles[mid]
        values = {f["key"]: p.get(f["key"]) for f in fields}
        values["label"] = p.get("label")
        values["short_label"] = p.get("short_label")
        modes_out.append({"mode_id": mid, "values": values, "profile": p})
    sel = mode_id if mode_id in PARALLEL_IDS else PARALLEL_IDS[0]
    return {
        "scope": "parallel",
        "readonly": False,
        "editable_modes": list(PARALLEL_IDS),
        "selected_mode": sel,
        "fields": fields,
        "modes": modes_out,
        "note": "Paralel evren paper kitabı — canlı Binance emirlerine dokunmaz.",
    }


def validate_live_patch(patch: dict[str, Any]) -> tuple[dict[str, str], list[str]]:
    errors: list[str] = []
    out: dict[str, str] = {}
    for key, val in patch.items():
        if key not in LIVE_EDITABLE_KEYS:
            errors.append(f"izin yok: {key}")
            continue
        meta = LIVE_KEY_META.get(key, {"type": "float"})
        try:
            coerced = _coerce(meta, val)
            if meta.get("type") == "bool":
                out[key] = "1" if coerced else "0"
            elif meta.get("type") == "int":
                out[key] = str(int(round(float(coerced))))
            else:
                out[key] = str(coerced)
        except (TypeError, ValueError) as exc:
            errors.append(f"{key}: {exc}")
    return out, errors


def _write_scenario_keys(updates: dict[str, str]) -> tuple[list[str], str]:
    if not _LIVE_SCENARIO.is_file():
        raise ValueError("senaryo dosyası yok")
    lines = _LIVE_SCENARIO.read_text(encoding="utf-8").splitlines()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    backup = _ROOT / "data" / "backups" / f"panel_live_{stamp}.env.bak"
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(_LIVE_SCENARIO, backup)
    changed: list[str] = []
    for key, val in updates.items():
        pat = re.compile(rf"^{re.escape(key)}=.*")
        new_line = f"{key}={val}"
        found = False
        for i, line in enumerate(lines):
            if pat.match(line):
                if line != new_line:
                    lines[i] = new_line
                    changed.append(key)
                found = True
                break
        if not found:
            lines.append(new_line)
            changed.append(key)
    if not changed:
        return [], str(backup)
    _LIVE_SCENARIO.write_text("\n".join(lines) + "\n", encoding="utf-8")
    for key in changed:
        os.environ[key] = updates[key]
    return changed, str(backup)


def apply_live_settings(patch: dict[str, Any]) -> dict[str, Any]:
    cleaned, errors = validate_live_patch(patch)
    if errors:
        raise ValueError("; ".join(errors))
    if not cleaned:
        raise ValueError("uygulanacak alan yok")
    changed, backup = _write_scenario_keys(cleaned)
    try:
        from elite_trader.system_checkpoint_md import on_live_settings

        on_live_settings(cleaned, source="apply_live_settings")
    except Exception:
        pass
    return {
        "scope": "live",
        "changed_keys": changed,
        "backup_path": backup,
        "scenario_file": str(_LIVE_SCENARIO.name),
        "applied": cleaned,
    }


def preview_live_patch(patch: dict[str, Any]) -> dict[str, Any]:
    cleaned, errors = validate_live_patch(patch)
    before = _scenario_env_map()
    after = {**before, **cleaned}
    return {
        "ok": not errors,
        "errors": errors,
        "before": {k: before.get(k) for k in cleaned},
        "after": {k: after.get(k) for k in cleaned},
        "hint": "Kaydet + Restart sonrası Ana Hat motoru yeni değerlerle çalışır.",
    }


def parse_prompt_to_live_patch(prompt: str) -> dict[str, str]:
    t = (prompt or "").strip().lower()
    if not t:
        return {}
    cur = _scenario_env_map()
    p: dict[str, str] = {}

    def f(key: str, val: float | int | str) -> None:
        if key in LIVE_EDITABLE_KEYS:
            p[key] = str(val)

    if re.search(r"az işlem|seçici|sıkı|filtre", t):
        f("ELITE_MIN_EDGE", round(float(cur.get("ELITE_MIN_EDGE", 0.045)) + 0.008, 4))
        f("ELITE_MIN_FORMULA_SCORE", round(float(cur.get("ELITE_MIN_FORMULA_SCORE", 0.52)) + 0.04, 3))
    if re.search(r"agresif|çok işlem|gevşek", t):
        f("ELITE_MIN_EDGE", round(max(0.02, float(cur.get("ELITE_MIN_EDGE", 0.045)) - 0.006), 4))
        f("ELITE_MIN_FORMULA_SCORE", round(max(0.35, float(cur.get("ELITE_MIN_FORMULA_SCORE", 0.52)) - 0.03), 3))
    if re.search(r"erken tp|tp85|kârı kilitle", t):
        f("ELITE_TP_TRIGGER_FRAC", round(max(0.5, float(cur.get("ELITE_TP_TRIGGER_FRAC", 0.98)) - 0.1), 3))
        f("ELITE_TP_STAKE_PCT", round(max(0.003, float(cur.get("ELITE_TP_STAKE_PCT", 0.01)) - 0.002), 4))
    if re.search(r"sıkı sl|koruma", t):
        f("ELITE_SL_STAKE_PCT", round(max(0.005, float(cur.get("ELITE_SL_STAKE_PCT", 0.015)) - 0.002), 4))
    if re.search(r"spike açık|spike", t) and "kapat" not in t:
        f("ELITE_SPIKE_QUICK_TP_ENABLED", "1")
        f("ELITE_SPIKE_QUICK_TP_MIN_AGE_SEC", round(max(5, float(cur.get("ELITE_SPIKE_QUICK_TP_MIN_AGE_SEC", 40)) - 5), 1))
    if re.search(r"spike kapalı", t):
        f("ELITE_SPIKE_QUICK_TP_ENABLED", "0")
    if re.search(r"stale", t):
        f("ELITE_STALE_TP_ENABLED", "1")
    m = re.search(r"(\d+)\s*(açık|pozisyon|slot)", t)
    if m:
        f("ELITE_MAX_OPEN", int(m.group(1)))
    m2 = re.search(r"cooldown\s*(\d+)", t)
    if m2:
        f("ELITE_MARKET_COOLDOWN_MIN", int(m2.group(1)))
    if re.search(r"net\s*k[aâ]r|ücret|fee|komisyon|binance", t):
        f("ELITE_ENTRY_REQUIRE_NET_TP", "1")
        f("ELITE_TP_NET_AFTER_FEE", "1")
    if re.search(r"günlük\s*2|2\s*[x×]|2x", t):
        f("ELITE_DAILY_TARGET_MULT", "2.0")
    m_pct = re.search(r"(%?\s*50|0\.5)\s*%?\s*(aktif|sermaye|piyasa)", t)
    if m_pct or re.search(r"aktif\s*%?\s*50|sermaye\s*%?\s*50", t):
        f("ELITE_ACTIVE_CAPITAL_PCT", "0.50")
    m_min = re.search(r"min\s*net\s*\$?\s*([\d.]+)", t)
    if m_min:
        f("ELITE_ENTRY_MIN_NET_USD", float(m_min.group(1)))
    m_fee = re.search(r"fee\s*cover\s*([\d.]+)|ücret\s*çarpan\s*([\d.]+)", t)
    if m_fee:
        v = m_fee.group(1) or m_fee.group(2)
        f("ELITE_TP_FEE_COVER_MULT", float(v))
    return p


def apply_live_prompt(prompt: str, *, dry_run: bool = False) -> dict[str, Any]:
    patch = parse_prompt_to_live_patch(prompt)
    if not patch:
        return {"ok": False, "error": "Prompt’tan Ana Hat ayarı çıkarılamadı", "patch": {}}
    prev = preview_live_patch(patch)
    if not prev["ok"]:
        return {"ok": False, "error": "; ".join(prev["errors"]), "patch": patch, "preview": prev}
    if dry_run:
        return {"ok": True, "dry_run": True, "patch": patch, "preview": prev}
    result = apply_live_settings(patch)
    return {"ok": True, "patch": patch, "preview": prev, "result": result}


def restart_live_bot() -> dict[str, Any]:
    """
    Güvenli restart — port-aware ctl script (9005 / 9006 / 9007).
    """
    import subprocess

    port = os.environ.get("BINANCE_ELITE_PORT", "9005").strip()
    ctl_name = {
        "9007": "elite_9007_process_ctl.sh",
        "9006": "elite_9006_process_ctl.sh",
    }.get(port, "elite_9005_process_ctl.sh")
    ctl = _ROOT / "scripts" / ctl_name
    if not ctl.is_file():
        raise FileNotFoundError(str(ctl))
    subprocess.Popen(
        ["/bin/bash", str(ctl), "restart"],
        cwd=str(_ROOT),
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        from elite_trader.system_checkpoint_md import on_restart

        on_restart(source=f"elite_{port}_ctl", note="api_settings_restart")
    except Exception:
        pass
    label = f"Elite {port}"
    return {
        "restarted": True,
        "scheduled": True,
        "message": f"{label} ~10 sn içinde güvenli restart (tek örnek)",
        "pid": None,
        "port": port,
        "ctl": ctl_name,
    }


def get_settings(scope: str = "parallel", mode_id: str | None = None) -> dict[str, Any]:
    scope = (scope or "parallel").strip().lower()
    if scope == "live":
        return live_settings_bundle()
    if scope.startswith("mode:"):
        mode_id = scope.split(":", 1)[1]
    return parallel_settings_bundle(mode_id)


def validate_parallel_patch(patch: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    out: dict[str, Any] = {}
    field_map = {f["key"]: f for f in PARALLEL_FIELDS}
    for key, val in patch.items():
        if key in ("label", "short_label") and isinstance(val, str):
            out[key] = val[:80]
            continue
        if key == "description":
            out[key] = str(val)[:500]
            continue
        f = field_map.get(key)
        if not f:
            errors.append(f"bilinmeyen alan: {key}")
            continue
        try:
            out[key] = _coerce(f, val)
        except (TypeError, ValueError) as exc:
            errors.append(f"{key}: {exc}")
    return out, errors


def apply_parallel_settings(mode_id: str, patch: dict[str, Any]) -> dict[str, Any]:
    cleaned, errors = validate_parallel_patch(patch)
    if errors:
        raise ValueError("; ".join(errors))
    profile = save_profile(mode_id, cleaned)
    try:
        from elite_trader.system_checkpoint_md import on_profile_patch

        on_profile_patch(mode_id, cleaned, source="apply_parallel_settings")
    except Exception:
        pass
    return {"mode_id": mode_id, "profile": profile, "applied": cleaned}


def preview_parallel_patch(mode_id: str, patch: dict[str, Any]) -> dict[str, Any]:
    cleaned, errors = validate_parallel_patch(patch)
    before = get_profile(mode_id) or {}
    after = {**before, **cleaned}
    return {
        "ok": not errors,
        "errors": errors,
        "mode_id": mode_id,
        "before": {k: before.get(k) for k in cleaned},
        "after": {k: after.get(k) for k in cleaned},
        "hint": "Onay sonrası yalnızca paralel paper motoru güncellenir.",
    }


def parse_prompt_to_patch(prompt: str, mode_id: str) -> dict[str, Any]:
    """Kural tabanlı prompt → paralel mod patch (LLM/API yok)."""
    t = (prompt or "").strip().lower()
    if not t:
        return {}
    p: dict[str, Any] = {}
    prof = get_profile(mode_id) or {}

    def bump(key: str, delta: float, lo: float, hi: float) -> None:
        base = float(prof.get(key, 1.0))
        p[key] = round(max(lo, min(hi, base + delta)), 4)

    if re.search(r"az işlem|daha az|seçici|sıkı|filtre|kaliteli", t):
        bump("entry_min_edge_mult", 0.06, 0.7, 1.5)
        bump("entry_min_formula_mult", 0.05, 0.7, 1.5)
        p["entry_skip_cautious"] = True
    if re.search(r"çok işlem|agresif|gevşek|fazla işlem|hızlı giriş", t):
        bump("entry_min_edge_mult", -0.08, 0.7, 1.5)
        bump("entry_min_formula_mult", -0.06, 0.7, 1.5)
        p["entry_stake_mult"] = min(1.5, float(prof.get("entry_stake_mult", 1)) + 0.05)
    if re.search(r"erken tp|kârı kilitle|tp85|küçük tp", t):
        p["tp_trigger_frac"] = max(0.5, float(prof.get("tp_trigger_frac", 0.98)) - 0.08)
        p["tp_stake_pct"] = max(0.003, float(prof.get("tp_stake_pct", 0.01)) - 0.001)
    if re.search(r"geniş tp|büyük tp|tp bekle", t):
        p["tp_trigger_frac"] = min(1.0, float(prof.get("tp_trigger_frac", 0.98)) + 0.05)
    if re.search(r"sıkı sl|küçük sl|koruma|kalkan", t):
        p["sl_stake_pct"] = max(0.005, float(prof.get("sl_stake_pct", 0.015)) - 0.002)
    if re.search(r"geniş sl|büyük sl", t):
        p["sl_stake_pct"] = min(0.04, float(prof.get("sl_stake_pct", 0.015)) + 0.003)
    if re.search(r"spike|şimşek|hızlı çıkış|scalp", t):
        p["spike_enabled"] = True
        p["spike_min_age_sec"] = max(10, float(prof.get("spike_min_age_sec", 40)) - 5)
        p["stale_min_age_min"] = max(0.25, float(prof.get("stale_min_age_min", 2)) - 0.25)
    if re.search(r"stale|bekleme|flat", t):
        p["stale_enabled"] = True
    if re.search(r"spike kapalı|spike kapat", t):
        p["spike_enabled"] = False
    if re.search(r"strong|güçlü sinyal", t):
        p["entry_min_strength"] = "Strong"
    if re.search(r"medium|orta sinyal", t):
        p["entry_min_strength"] = "Medium"
    if re.search(r"max açık|pozisyon say", t):
        m = re.search(r"(\d+)\s*(açık|pozisyon|slot)", t)
        if m:
            p["entry_max_open"] = int(m.group(1))

    if not p and len(t) > 10:
        p["description"] = (prof.get("description") or "") + f" [prompt: {prompt[:120]}]"
    return p


def reset_parallel_settings(mode_id: str) -> dict[str, Any]:
    profile = reset_profile(mode_id)
    return {"mode_id": mode_id, "profile": profile}


def apply_prompt(mode_id: str, prompt: str, *, dry_run: bool = False) -> dict[str, Any]:
    if mode_id not in PARALLEL_IDS:
        raise ValueError(f"unknown mode: {mode_id}")
    patch = parse_prompt_to_patch(prompt, mode_id)
    if not patch:
        return {
            "ok": False,
            "error": "Prompt’tan ayar çıkarılamadı — örnek: «daha seçici giriş», «spike açık», «erken tp»",
            "patch": {},
        }
    prev = preview_parallel_patch(mode_id, patch)
    if not prev["ok"]:
        return {"ok": False, "error": "; ".join(prev["errors"]), "patch": patch, "preview": prev}
    if dry_run:
        return {"ok": True, "dry_run": True, "patch": patch, "preview": prev}
    applied = apply_parallel_settings(mode_id, patch)
    return {"ok": True, "patch": patch, "preview": prev, "result": applied}
