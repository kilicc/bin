"""Zarar kurtarma — ters yön hedge veya erken çıkış değerlendirmesi."""
from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from enum import Enum
from typing import Any

import momentum_scanner as ms

from elite_trader.pnl_engine import PnLEngine


class RecoveryAction(Enum):
    NONE = "none"
    CLOSE_ORIGINAL = "close_original"
    OPEN_HEDGE = "open_hedge"
    CLOSE_BOTH = "close_both"


@dataclass
class RecoveryPlan:
    action: RecoveryAction
    reason: str = ""
    hedge_side: str | None = None
    hedge_stake: float = 0.0
    hedge_entry: float = 0.0


def _hedge_trigger_pct(*, proactive: bool = False) -> float:
    key = "ELITE_HEDGE_PROACTIVE_PCT" if proactive else "ELITE_HEDGE_TRIGGER_PCT"
    default = "0.006" if proactive else "0.010"
    try:
        return float(os.getenv(key, default))
    except ValueError:
        return 0.006 if proactive else 0.010


def _hedge_proactive_enabled() -> bool:
    return os.getenv("ELITE_HEDGE_PROACTIVE", "1").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def _hedge_frac() -> float:
    try:
        return float(os.getenv("ELITE_HEDGE_STAKE_FRAC", "0.40"))
    except ValueError:
        return 0.40


def _leg_type(pos: Any) -> str:
    try:
        lt = pos["leg_type"]
        return str(lt) if lt else "primary"
    except (KeyError, IndexError, TypeError):
        return "primary"


def evaluate_recovery(
    conn: sqlite3.Connection,
    pos: sqlite3.Row,
    yes_price: float,
    *,
    client=None,
    proactive: bool = False,
) -> RecoveryPlan:
    """Primary pozisyon için kurtarma planı."""
    if _leg_type(pos) != "primary":
        return RecoveryPlan(RecoveryAction.NONE)

    hedge_id = None
    try:
        hedge_id = pos["hedge_of_id"]
    except (KeyError, IndexError):
        pass

    side = pos["side"]
    entry = float(pos["entry_price"])
    stake = float(pos["stake_usd"])
    contracts = float(pos["contracts"] or 0)
    market_id = str(pos["market_id"])
    pos_id = int(pos["id"])

    unreal = PnLEngine.unrealized(side, entry, yes_price, stake, contracts=contracts)
    use_proactive = proactive and _hedge_proactive_enabled()
    trigger = -stake * _hedge_trigger_pct(proactive=use_proactive)

    # Mevcut hedge bacak
    hedge_row = conn.execute(
        """
        SELECT id, side, entry_price, stake_usd, contracts
        FROM positions
        WHERE hedge_of_id=? AND closed_at IS NULL AND leg_type='hedge'
        """,
        (pos_id,),
    ).fetchone()

    if hedge_row:
        h_side = hedge_row["side"]
        h_entry = float(hedge_row["entry_price"])
        h_contracts = float(hedge_row["contracts"] or 0)
        h_unreal = PnLEngine.unrealized(
            h_side, h_entry, yes_price, float(hedge_row["stake_usd"]), contracts=h_contracts
        )
        net = unreal + h_unreal
        if net >= stake * 0.001:
            return RecoveryPlan(
                RecoveryAction.CLOSE_BOTH,
                reason=f"net_recovery ${net:.2f}",
            )
        return RecoveryPlan(RecoveryAction.NONE, reason="hedge_open_waiting")

    if unreal > trigger:
        return RecoveryPlan(RecoveryAction.NONE)

    # Karşı taraf edge
    opp_side = "NO" if side == "YES" else "YES"
    opp_entry = (1.0 - yes_price) if opp_side == "NO" else yes_price
    sig = ms.signal_for_price(yes_price)
    if sig is None:
        return RecoveryPlan(
            RecoveryAction.CLOSE_ORIGINAL,
            reason=f"adverse ${unreal:.2f} no_opp_edge",
        )
    sig_side, sig_entry, edge = sig
    if sig_side != opp_side or edge < float(os.getenv("ELITE_MIN_EDGE", "0.055")) * 0.8:
        return RecoveryPlan(
            RecoveryAction.CLOSE_ORIGINAL,
            reason=f"adverse ${unreal:.2f} weak_hedge_edge",
        )

    hedge_stake = min(stake * _hedge_frac(), stake)
    return RecoveryPlan(
        RecoveryAction.OPEN_HEDGE,
        reason=f"adverse ${unreal:.2f} hedge_edge={edge:.3f}",
        hedge_side=opp_side,
        hedge_stake=hedge_stake,
        hedge_entry=sig_entry,
    )


def has_open_hedge(conn: sqlite3.Connection, primary_id: int) -> bool:
    row = conn.execute(
        """
        SELECT 1 FROM positions
        WHERE hedge_of_id=? AND closed_at IS NULL AND leg_type='hedge'
        """,
        (primary_id,),
    ).fetchone()
    return row is not None
