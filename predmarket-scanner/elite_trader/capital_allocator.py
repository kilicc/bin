"""Sermaye tahsisi — aktif işlem için bakiyenin belirli yüzdesi."""
from __future__ import annotations

import os


def active_capital_pct() -> float:
    try:
        return float(os.getenv("ELITE_ACTIVE_CAPITAL_PCT", "0.50"))
    except ValueError:
        return 0.50


def _max_stake_cap(max_stake: float) -> float:
    """0 veya negatif → üst sınır yok."""
    if max_stake <= 0:
        return float("inf")
    return max_stake


def wr_stake_multiplier(win_rate: float) -> float:
    """Kazanma oranı baseline'a göre stake çarpanı."""
    try:
        baseline = float(os.getenv("ELITE_ASSUMED_WR", "0.58"))
        min_m = float(os.getenv("ELITE_STAKE_WR_MIN_MULT", "0.45"))
        max_m = float(os.getenv("ELITE_STAKE_WR_MAX_MULT", "4.0"))
    except ValueError:
        baseline, min_m, max_m = 0.58, 0.45, 4.0
    if baseline <= 1e-6:
        return 1.0
    return max(min_m, min(max_m, win_rate / baseline))


def effective_win_rate(observed: float | None) -> float:
    if observed is not None:
        return observed
    try:
        return float(os.getenv("ELITE_ASSUMED_WR", "0.58"))
    except ValueError:
        return 0.58


def compute_stake(
    equity: float,
    open_stakes: list[float],
    *,
    kelly_stake: float,
    max_open: int,
    min_stake: float,
    max_stake: float,
    win_rate: float | None = None,
    active_capital_pct_override: float | None = None,
) -> float:
    """
    deployable = equity * active_pct
    Stake: min_stake floor, üst sınır (opsiyonel), kalan sermaye ve WR ölçekli Kelly.
    """
    pct = (
        float(active_capital_pct_override)
        if active_capital_pct_override is not None
        else active_capital_pct()
    )
    deployable = equity * pct
    used = sum(open_stakes)
    remaining = max(0.0, deployable - used)
    open_n = len(open_stakes)
    if open_n >= max_open:
        return 0.0
    slots_left = max(1, max_open - open_n)
    try:
        floor = float(os.getenv("ELITE_MIN_STAKE_FLOOR_USD", "80"))
    except ValueError:
        floor = 80.0
    if remaining < floor:
        return 0.0

    wr = effective_win_rate(win_rate)
    wr_mult = wr_stake_multiplier(wr)
    per_slot = remaining / slots_left
    cap_hi = _max_stake_cap(max_stake)

    base = max(kelly_stake * wr_mult, min_stake)
    stake = min(cap_hi, remaining, base)
    if per_slot >= floor:
        stake = min(stake, per_slot)
    # Kalan sermaye min_stake altındaysa küçük pozisyon (tamamen kilitleme)
    if remaining < min_stake:
        stake = min(cap_hi, remaining)
    else:
        stake = max(min_stake, stake)
    if cap_hi < float("inf"):
        stake = min(cap_hi, stake)
    if stake < floor:
        return 0.0
    return stake


def snapshot(
    equity: float,
    open_stakes: list[float],
    *,
    win_rate: float | None = None,
) -> dict[str, float]:
    pct = active_capital_pct()
    deployable = equity * pct
    used = sum(open_stakes)
    wr = effective_win_rate(win_rate)
    return {
        "active_capital_pct": pct,
        "deployable_usd": round(deployable, 2),
        "deployed_usd": round(used, 2),
        "deploy_pct_of_cap": round(used / deployable, 4) if deployable > 0 else 0.0,
        "remaining_usd": round(max(0, deployable - used), 2),
        "win_rate": round(wr, 4),
        "wr_stake_mult": round(wr_stake_multiplier(wr), 3),
    }
