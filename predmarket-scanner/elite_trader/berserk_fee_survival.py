"""Berserk V2 — fee/gross survival and recovery mode."""
from __future__ import annotations

import time
from typing import Any

_session: dict[str, Any] = {
    "gross_wins": 0.0,
    "total_fees": 0.0,
    "net_pnl": 0.0,
    "trade_count": 0,
    "spread_penalty_count": 0,
    "slippage_penalty_count": 0,
    "session_start_ts": time.time(),
    "recovery_mode": False,
}


def reset_session() -> None:
    global _session
    _session = {
        "gross_wins": 0.0,
        "total_fees": 0.0,
        "net_pnl": 0.0,
        "trade_count": 0,
        "spread_penalty_count": 0,
        "slippage_penalty_count": 0,
        "session_start_ts": time.time(),
        "recovery_mode": False,
    }


def record_trade_close(closed: dict[str, Any]) -> None:
    pnl = float(closed.get("final_pnl") or closed.get("net_pnl") or 0)
    fees = float(closed.get("total_fees") or 0)
    _session["trade_count"] += 1
    _session["total_fees"] += fees
    _session["net_pnl"] += pnl
    if pnl > 0:
        _session["gross_wins"] += pnl
    if str(closed.get("spread_risk_level") or "") not in ("none", ""):
        _session["spread_penalty_count"] += 1
    if float(closed.get("slippage_damage_score") or 0) > 0.3:
        _session["slippage_penalty_count"] += 1


def _ratios() -> tuple[float, float]:
    gross = max(0.01, float(_session["gross_wins"]))
    fees = max(0.01, float(_session["total_fees"]))
    fee_gross = fees / gross if gross > 0.01 else 0.0
    gross_fee = gross / fees if fees > 0.01 else 99.0
    return fee_gross, gross_fee


def assess_fee_survival(profile: dict[str, Any]) -> dict[str, Any]:
    fee_gross, gross_fee = _ratios()
    elapsed_min = max(0.1, (time.time() - float(_session["session_start_ts"])) / 60.0)
    tc = max(1, int(_session["trade_count"]))
    gross = float(_session["gross_wins"])
    fees = float(_session["total_fees"])
    net = float(_session["net_pnl"])

    spread_damage = _session["spread_penalty_count"] / tc
    slip_damage = _session["slippage_penalty_count"] / tc

    recovery_thresh = float(profile.get("berserk_recovery_fee_gross_pct") or 0.75)
    mode = "normal"
    stake_mult = 1.0
    min_score_boost = 0
    prefer_limit = False
    market_disabled = False
    tp_min_bump = 0.0
    speed_throttle = 1.0

    if fee_gross <= 0.45:
        mode = "normal"
    elif fee_gross <= 0.60:
        mode = "caution"
        tp_min_bump = 0.0003
    elif fee_gross <= recovery_thresh:
        mode = "throttle"
        stake_mult = 0.70
        prefer_limit = True
        speed_throttle = 0.70
    else:
        mode = "recovery"
        stake_mult = 0.50
        min_score_boost = 5
        prefer_limit = True
        market_disabled = True
        _session["recovery_mode"] = True

    if gross_fee < 1.4:
        prefer_limit = True

    return {
        "fee_gross_ratio": round(fee_gross, 4),
        "gross_fee_ratio": round(gross_fee, 4),
        "fee_per_minute": round(fees / elapsed_min, 4),
        "net_pnl_per_minute": round(net / elapsed_min, 4),
        "avg_fee_per_trade": round(fees / tc, 4),
        "avg_net_after_fee": round(net / tc, 4),
        "spread_damage_score": round(spread_damage, 4),
        "slippage_damage_score": round(slip_damage, 4),
        "fee_survival_mode": mode,
        "recovery_mode": mode == "recovery",
        "fee_stake_mult": stake_mult,
        "fee_min_score_boost": min_score_boost,
        "fee_prefer_limit": prefer_limit,
        "fee_market_disabled": market_disabled,
        "fee_tp_min_bump": tp_min_bump,
        "fee_speed_throttle": speed_throttle,
    }


def session_snapshot() -> dict[str, Any]:
    fee_gross, gross_fee = _ratios()
    return {
        "trade_count": _session["trade_count"],
        "fee_gross_ratio": round(fee_gross, 4),
        "gross_fee_ratio": round(gross_fee, 4),
        "recovery_mode": bool(_session.get("recovery_mode")),
    }
