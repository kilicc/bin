"""MEGA/Berserk2 — 24h coin watch: ★ kârlı coin kitabı, alt3 veto (SL yok)."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, str(default)))
    except ValueError:
        return default


def _env_int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, str(default)))
    except ValueError:
        return default


def _env_bool(key: str, default: bool = False) -> bool:
    v = os.getenv(key, "1" if default else "0").strip().lower()
    return v in ("1", "true", "yes")


def registry_path(data_dir: Path | None = None) -> Path:
    if data_dir is None:
        try:
            from elite_trader.mega_live import mega_instance_data_dir

            data_dir = mega_instance_data_dir()
        except Exception:
            data_dir = Path(__file__).resolve().parent.parent / "data" / "mega_9006"
    return data_dir / "mega_coin_watch_registry.json"


def _load_raw(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"symbols": {}, "updated_at": None}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"symbols": {}, "updated_at": None}


def load_registry(data_dir: Path | None = None) -> dict[str, Any]:
    return _load_raw(registry_path(data_dir))


def save_registry(reg: dict[str, Any], data_dir: Path | None = None) -> None:
    path = registry_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    reg["updated_at"] = time.time()
    path.write_text(
        json.dumps(reg, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def apply_rank_report(report: dict[str, Any], data_dir: Path | None = None) -> dict[str, Any]:
    """24h rank çıktısından registry güncelle."""
    reg = load_registry(data_dir)
    symbols: dict[str, Any] = reg.setdefault("symbols", {})
    now = time.time()
    star_hours = _env_float("MEGA_STAR_TTL_HOURS", 24.0)
    veto_hours = _env_float("MEGA_BOTTOM_VETO_HOURS", 48.0)
    for sym in report.get("stars") or []:
        s = str(sym).upper()
        entry = symbols.setdefault(s, {})
        entry["starred"] = True
        entry["starred_until"] = now + star_hours * 3600.0
        entry["boost_rules"] = report.get("star_boost_by_symbol", {}).get(s) or []
        entry["behavior_playbook"] = (
            report.get("star_playbook_by_symbol", {}).get(s) or {}
        )
        row = next(
            (r for r in report.get("ranked") or [] if r.get("symbol") == s),
            {},
        )
        entry["profit_yield"] = row.get("profit_yield")
        entry["net_pnl"] = row.get("net_pnl")
        entry.pop("block_entry", None)
    for sym in report.get("bottom3") or []:
        s = str(sym).upper()
        entry = symbols.setdefault(s, {})
        entry["bottom3"] = True
        entry["veto_until"] = now + veto_hours * 3600.0
        prev = int(entry.get("bottom_streak") or 0)
        entry["bottom_streak"] = prev + 1
        if entry["bottom_streak"] >= _env_int("MEGA_BOTTOM_BLOCK_STREAK", 2):
            entry["block_entry"] = True
        entry["bottom_rules"] = report.get("bottom_rules_by_symbol", {}).get(s) or []
    reg["last_rank_at"] = report.get("generated_at")
    reg["last_stars"] = list(report.get("stars") or [])
    reg["last_bottom3"] = list(report.get("bottom3") or [])
    save_registry(reg, data_dir)
    return reg


def _sym_entry(sym: str, data_dir: Path | None = None) -> dict[str, Any]:
    s = str(sym or "").upper()
    if not s:
        return {}
    reg = load_registry(data_dir)
    return dict((reg.get("symbols") or {}).get(s) or {})


def is_starred(sym: str, data_dir: Path | None = None) -> bool:
    e = _sym_entry(sym, data_dir)
    if not e.get("starred"):
        return False
    until = float(e.get("starred_until") or 0)
    return until <= 0 or time.time() < until


def is_bottom_blocked(sym: str, data_dir: Path | None = None) -> tuple[bool, str]:
    e = _sym_entry(sym, data_dir)
    if e.get("block_entry"):
        return True, "coin_bottom_block"
    until = float(e.get("veto_until") or 0)
    if until > 0 and time.time() < until:
        return True, "coin_bottom_veto"
    return False, ""


def get_symbol_playbook(sym: str, data_dir: Path | None = None) -> dict[str, Any]:
    """★ coin — geçmiş hareket/çıkış kitabı (kârlı coin bilgisi)."""
    if not is_starred(sym, data_dir):
        return {}
    e = _sym_entry(sym, data_dir)
    pb = e.get("behavior_playbook")
    return dict(pb) if isinstance(pb, dict) else {}


def get_symbol_boost(sym: str, data_dir: Path | None = None) -> dict[str, Any]:
    """Giriş skoru / stake çarpanı — yıldızlı coinler."""
    if not is_starred(sym, data_dir):
        return {"stake_mult": 1.0, "min_score_delta": 0, "starred": False}
    e = _sym_entry(sym, data_dir)
    rules = e.get("boost_rules") or []
    stake_mult = 1.0
    min_score_delta = 0
    for r in rules:
        if not isinstance(r, dict):
            continue
        stake_mult += float(r.get("stake_mult_add") or 0)
        min_score_delta += int(r.get("min_score_delta") or 0)
    cap = _env_float("MEGA_STAR_BOOST_MAX_MULT", 1.08)
    stake_mult = min(cap, max(1.0, stake_mult))
    return {
        "stake_mult": round(stake_mult, 4),
        "min_score_delta": min_score_delta,
        "starred": True,
        "behavior_playbook": get_symbol_playbook(sym, data_dir),
        "profit_yield": e.get("profit_yield"),
    }


def apply_star_entry_hints(
    sym: str,
    side: str,
    signal: dict[str, Any],
    *,
    data_dir: Path | None = None,
) -> dict[str, Any]:
    """
    Yıldızlı kârlı coin — sinyali geçmiş hareket kitabıyla hizala.
    Dönüş: stake_mult, min_score_delta, alignment, playbook, open_behavior.
    """
    out: dict[str, Any] = {
        "starred": False,
        "stake_mult": 1.0,
        "min_score_delta": 0,
        "alignment": "",
        "playbook": {},
        "open_behavior": {},
    }
    boost = get_symbol_boost(sym, data_dir)
    if not boost.get("starred"):
        return out
    out["starred"] = True
    out["stake_mult"] = float(boost.get("stake_mult") or 1.0)
    out["min_score_delta"] = int(boost.get("min_score_delta") or 0)
    pb = get_symbol_playbook(sym, data_dir)
    out["playbook"] = pb
    side_u = str(side or "").upper()
    pref = str(pb.get("preferred_side") or "").upper()
    pref_share = float(pb.get("preferred_side_share") or 0.0)
    is_flash = bool(
        signal.get("mega_flash_reversal")
        or signal.get("flash_reversal")
        or signal.get("mega_flash_pump")
    )
    aligned_side = pref and side_u == pref
    caution_side = (
        pref
        and side_u in ("LONG", "SHORT")
        and side_u != pref
        and pref_share >= _env_float("MEGA_STAR_SIDE_CAUTION_SHARE", 0.55)
    )
    if aligned_side:
        out["alignment"] = "star_side_aligned"
        out["min_score_delta"] -= _env_int("MEGA_STAR_ALIGNED_SCORE_BONUS", 3)
        out["stake_mult"] = min(
            _env_float("MEGA_STAR_BOOST_MAX_MULT", 1.08),
            out["stake_mult"] * _env_float("MEGA_STAR_ALIGNED_STAKE_MULT", 1.04),
        )
    elif caution_side:
        out["alignment"] = "star_side_caution"
        out["min_score_delta"] += _env_int("MEGA_STAR_SIDE_CAUTION_SCORE", 5)
        out["stake_mult"] *= _env_float("MEGA_STAR_SIDE_CAUTION_STAKE_MULT", 0.94)
        if _env_bool("MEGA_STAR_BLOCK_COUNTER_SIDE", False):
            out["block_entry"] = True
            out["reject_tag"] = "star_side_mismatch"
    flash_share = float(pb.get("flash_share") or 0.0)
    if is_flash and flash_share >= 0.4:
        out["alignment"] = (out["alignment"] or "star") + "+flash_known"
        out["min_score_delta"] -= 2
    out["open_behavior"] = {
        "expects_spike_or_flash_exit": bool(pb.get("expects_spike_or_flash_exit")),
        "typical_exit": pb.get("typical_exit"),
        "avg_hold_sec_hint": pb.get("avg_win_duration_sec"),
        "btc_regime_hint": pb.get("btc_regime_when_winning"),
        "profitable_coin": True,
    }
    if _env_bool("MEGA_STAR_REQUIRE_SIDE_MATCH", False) and caution_side:
        out["block_entry"] = True
        out["reject_tag"] = "star_side_mismatch"
    return out


def get_symbol_penalty(sym: str, data_dir: Path | None = None) -> dict[str, Any]:
    blocked, tag = is_bottom_blocked(sym, data_dir)
    e = _sym_entry(sym, data_dir)
    min_score_delta = 0
    for r in e.get("bottom_rules") or []:
        if isinstance(r, dict):
            min_score_delta += int(r.get("min_score_delta") or 0)
    if blocked and min_score_delta == 0:
        min_score_delta = _env_int("MEGA_BOTTOM_MIN_SCORE_PENALTY", 4)
    return {
        "block_entry": blocked,
        "reject_tag": tag,
        "min_score_delta": min_score_delta,
    }
