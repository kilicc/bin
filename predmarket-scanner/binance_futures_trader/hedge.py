"""Futures hedge — ters yön bacak."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from enum import Enum

from binance_futures_trader import config as cfg


class RecoveryAction(Enum):
    NONE = "none"
    OPEN_HEDGE = "open_hedge"
    CLOSE_PRIMARY = "close_primary"


@dataclass
class RecoveryPlan:
    action: RecoveryAction
    reason: str = ""
    hedge_side: str | None = None
    hedge_stake: float = 0.0


def _unrealized(side: str, entry: float, cur: float, contracts: float) -> float:
    if side == "LONG":
        return contracts * (cur - entry)
    return contracts * (entry - cur)


def evaluate(
    pos: sqlite3.Row,
    cur_price: float,
    *,
    proactive: bool = False,
) -> RecoveryPlan:
    if not cfg.HEDGE_ENABLED:
        return RecoveryPlan(RecoveryAction.NONE)
    if (pos["leg_type"] or "primary") != "primary":
        return RecoveryPlan(RecoveryAction.NONE)

    stake = float(pos["stake_usd"])
    entry = float(pos["entry_price"])
    contracts = float(pos["contracts"])
    side = pos["side"]
    unreal = _unrealized(side, entry, cur_price, contracts)
    trigger_pct = cfg.HEDGE_TRIGGER_PCT * (0.5 if proactive and cfg.HEDGE_PROACTIVE else 1.0)
    trigger = -stake * trigger_pct

    if unreal > trigger:
        return RecoveryPlan(RecoveryAction.NONE)

    opp = "SHORT" if side == "LONG" else "LONG"
    return RecoveryPlan(
        RecoveryAction.OPEN_HEDGE,
        reason=f"adverse ${unreal:.2f}",
        hedge_side=opp,
        hedge_stake=stake * cfg.HEDGE_STAKE_FRAC,
    )


def has_hedge(conn: sqlite3.Connection, primary_id: int) -> bool:
    row = conn.execute(
        """
        SELECT 1 FROM positions
        WHERE hedge_of_id=? AND closed_at IS NULL AND leg_type='hedge'
        """,
        (primary_id,),
    ).fetchone()
    return row is not None
