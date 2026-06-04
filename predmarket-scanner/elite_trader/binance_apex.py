"""Binance 9005 — apex öğrenilmiş formül + WR ölçekli stake (2× günlük hedef)."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
_APEX_JSON = _ROOT / "data" / "apex_master" / "learned_formula.json"
_LESSONS = _ROOT / "data" / "elite_9005_trade_lessons.json"

_cached: dict[str, Any] | None = None


def invalidate_apex_cache() -> None:
    global _cached
    _cached = None


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, str(default)))
    except ValueError:
        return default


def load_apex_config(*, reload: bool = False) -> dict[str, Any]:
    global _cached
    if reload:
        invalidate_apex_cache()
    if _cached is not None:
        return _cached
    cfg: dict[str, Any] = {
        "target_equity_mult": _env_float("ELITE_DAILY_TARGET_MULT", 2.0),
        "active_capital_pct": _env_float("ELITE_ACTIVE_CAPITAL_PCT", 0.50),
        "min_edge": _env_float("ELITE_MIN_EDGE", 0.048),
        "min_formula_score": _env_float("ELITE_MIN_FORMULA_SCORE", 0.52),
        "avg_trader_wr": 0.58,
    }
    if _APEX_JSON.is_file():
        try:
            raw = json.loads(_APEX_JSON.read_text(encoding="utf-8"))
            cfg.update({k: raw[k] for k in raw if k in cfg or k.startswith("min_")})
            cfg["source"] = "apex_master/learned_formula.json"
        except Exception:
            cfg["source"] = "env_defaults"
    if _LESSONS.is_file():
        try:
            les = json.loads(_LESSONS.read_text(encoding="utf-8"))
            cfg["lessons_count"] = len(les) if isinstance(les, list) else len(les.get("trades", []))
        except Exception:
            pass
    _cached = cfg
    return cfg


def apex_entry_score(
    *,
    symbol: str,
    side: str,
    change_pct: float,
    formula_score: float,
    strength: str,
) -> tuple[float, dict[str, Any]]:
    """
    Başarı formülü bileşeni — momentum + skor + güç.
    Dönüş: (0..1 skor, bileşenler).
    """
    cfg = load_apex_config()
    move = abs(float(change_pct)) / 100.0
    mom_part = min(1.0, move * 35.0)
    fs_part = min(1.0, max(0.0, (formula_score - 0.45) / 0.25))
    str_part = {"Strong": 1.0, "Medium": 0.72, "Weak": 0.35}.get(strength, 0.4)
    sym_bias = float(cfg.get("symbol_bias", {}).get(symbol, 0.5)) if isinstance(
        cfg.get("symbol_bias"), dict
    ) else 0.5
    side_w = float(cfg.get("side_weights", {}).get(side, 0.5)) if isinstance(
        cfg.get("side_weights"), dict
    ) else 0.5
    total = (
        0.32 * mom_part
        + 0.28 * fs_part
        + 0.22 * str_part
        + 0.10 * sym_bias
        + 0.08 * side_w
    )
    parts = {
        "momentum": round(mom_part, 3),
        "formula": round(fs_part, 3),
        "strength": round(str_part, 3),
        "symbol_bias": round(sym_bias, 3),
        "side_bias": round(side_w, 3),
    }
    return round(min(1.0, total), 4), parts


def entry_allowed(
    *,
    symbol: str,
    side: str,
    change_pct: float,
    formula_score: float,
    strength: str,
) -> tuple[bool, str]:
    cfg = load_apex_config()
    if abs(float(change_pct)) < _env_float("ELITE_MIN_MOMENTUM_PCT", 0.14):
        return False, "low_momentum"
    if formula_score < cfg.get("min_formula_score", 0.52):
        return False, "low_formula"
    sc, _ = apex_entry_score(
        symbol=symbol,
        side=side,
        change_pct=change_pct,
        formula_score=formula_score,
        strength=strength,
    )
    min_apex = _env_float("ELITE_APEX_MIN_SCORE", 0.48)
    if sc < min_apex:
        return False, f"apex_score<{min_apex}"
    return True, "ok"


def dynamic_stake_bounds(equity: float, open_count: int, max_open: int) -> tuple[float, float]:
    """
    Min stake: aktif kasanın slot başına ~%8 (taban $25).
    Max: 0 → sınırsız (WR ile ölçeklenir).
    """
    pct = _env_float("ELITE_ACTIVE_CAPITAL_PCT", 0.50)
    deploy = equity * pct
    slots = max(1, max_open - open_count)
    per_slot = deploy / slots
    floor = max(_env_float("ELITE_MIN_STAKE_USD", 25), per_slot * 0.08)
    max_s = _env_float("ELITE_MAX_STAKE_USD", 0)
    return floor, max_s if max_s > 0 else float("inf")
