"""Pozisyon çıkışı — stale TP, kademeli runner, ROI hedefleri."""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from binance_futures_trader import config as cfg
from binance_futures_trader.portfolio import pct_move, unrealized_usd


class ExitKind(str, Enum):
    NONE = "none"
    STANDARD_TP = "standard_tp"
    STALE_TP = "stale_tp"
    STANDARD_SL = "standard_sl"
    TIER_PARTIAL = "tier_partial"
    TIER_FINAL = "tier_final"


@dataclass
class ExitPlan:
    kind: ExitKind
    close_fraction: float = 1.0
    reason: str = ""
    tier: int = 0
    roi_pct: float = 0.0
    move_pct: float = 0.0


def _parse_ts(iso: str | None) -> float | None:
    if not iso:
        return None
    try:
        s = iso.replace("Z", "+00:00")
        return datetime.fromisoformat(s).timestamp()
    except Exception:
        return None


def position_age_sec(opened_at: str | None) -> float:
    t0 = _parse_ts(opened_at)
    if t0 is None:
        return 0.0
    return max(0.0, datetime.now(timezone.utc).timestamp() - t0)


def roi_on_stake(
    side: str,
    entry: float,
    cur: float,
    contracts: float,
    stake: float,
) -> float:
    if stake <= 0:
        return 0.0
    upnl = unrealized_usd(side, entry, contracts, cur)
    return upnl / stake


def is_runner_candidate(score: float, confidence: float, strategies: str) -> bool:
    """Güçlü sinyal → %10/%20/%30 kademeli TP."""
    if abs(score) < cfg.RUNNER_MIN_SCORE:
        return False
    if confidence < cfg.RUNNER_MIN_CONF:
        return False
    strat = (strategies or "").upper()
    momentum_hits = sum(
        1 for tag in ("MOM3", "MOM", "BURST", "EMA", "VOL") if tag in strat
    )
    return momentum_hits >= cfg.RUNNER_MIN_MOM_TAGS


def evaluate_exit(
    pos: dict[str, Any],
    cur: float,
    *,
    age_sec: float | None = None,
) -> ExitPlan:
    side = str(pos.get("side") or "LONG")
    entry = float(pos.get("entry_price") or 0)
    contracts = float(pos.get("contracts") or 0)
    stake = float(pos.get("stake_usd") or 0)
    tpf = float(pos.get("tp_frac") or cfg.TP_PCT)
    slf = float(pos.get("sl_frac") or cfg.SL_PCT)
    leg = str(pos.get("leg_type") or "primary")
    runner = int(pos.get("runner_mode") or 0) == 1
    tp_stage = int(pos.get("tp_stage") or 0)

    if entry <= 0 or cur <= 0 or contracts <= 0:
        return ExitPlan(ExitKind.NONE)

    move = pct_move(side, entry, cur)
    roi = roi_on_stake(side, entry, cur, contracts, stake)
    move_pct = move * 100
    roi_pct = roi * 100
    age = age_sec if age_sec is not None else position_age_sec(pos.get("opened_at"))
    sl_eff = slf + cfg.SL_BUFFER_PCT

    if age < cfg.SL_MIN_HOLD_SEC:
        pass
    elif move <= -sl_eff:
        return ExitPlan(
            ExitKind.STANDARD_SL,
            close_fraction=1.0,
            reason="SL",
            move_pct=move_pct,
            roi_pct=roi_pct,
        )

    stale = leg == "primary" and age >= cfg.STALE_MIN_AGE_SEC
    try:
        stale_max_roi = float(os.getenv("BN_FUT_STALE_MAX_ROI", "0.006"))
    except ValueError:
        stale_max_roi = 0.006
    if stale and roi > stale_max_roi:
        stale = False

    if runner and leg == "primary":
        tiers = cfg.TIER_ROI_PCTS
        fracs = cfg.TIER_CLOSE_FRACS
        for i, target in enumerate(tiers):
            if tp_stage > i:
                continue
            if roi < target:
                break
            frac = fracs[i] if i < len(fracs) else (1.0 / len(tiers))
            is_last = i >= len(tiers) - 1
            return ExitPlan(
                ExitKind.TIER_FINAL if is_last else ExitKind.TIER_PARTIAL,
                close_fraction=min(1.0, max(0.05, frac)),
                reason=f"TP_TIER_{int(target * 100)}",
                tier=i + 1,
                roi_pct=roi_pct,
                move_pct=move_pct,
            )
        if move >= cfg.RUNNER_MAX_MOVE_PCT:
            return ExitPlan(
                ExitKind.TIER_FINAL,
                close_fraction=1.0,
                reason="RUNNER_CEILING",
                move_pct=move_pct,
                roi_pct=roi_pct,
            )
        if stale and move >= cfg.STALE_TP_MOVE_PCT:
            return ExitPlan(
                ExitKind.STALE_TP,
                close_fraction=1.0,
                reason="STALE_TP",
                move_pct=move_pct,
                roi_pct=roi_pct,
            )
        if stale and roi >= cfg.STALE_TP_ROI_PCT:
            return ExitPlan(
                ExitKind.STALE_TP,
                close_fraction=1.0,
                reason="STALE_TP_ROI",
                move_pct=move_pct,
                roi_pct=roi_pct,
            )
        return ExitPlan(ExitKind.NONE)

    if stale and move >= cfg.STALE_TP_MOVE_PCT:
        return ExitPlan(
            ExitKind.STALE_TP,
            close_fraction=1.0,
            reason="STALE_TP",
            move_pct=move_pct,
            roi_pct=roi_pct,
        )

    if stale and roi >= cfg.STALE_TP_ROI_PCT:
        return ExitPlan(
            ExitKind.STALE_TP,
            close_fraction=1.0,
            reason="STALE_TP_ROI",
            move_pct=move_pct,
            roi_pct=roi_pct,
        )

    if not stale and move >= tpf:
        return ExitPlan(
            ExitKind.STANDARD_TP,
            close_fraction=1.0,
            reason="TP",
            move_pct=move_pct,
            roi_pct=roi_pct,
        )

    return ExitPlan(ExitKind.NONE)
