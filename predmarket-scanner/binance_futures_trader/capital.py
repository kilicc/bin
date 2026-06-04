"""Sermaye — bakiyenin %50'si aktif; WR ile stake ölçekleme."""
from __future__ import annotations

import sqlite3

from binance_futures_trader import config as cfg
from binance_futures_trader.risk_rules import risk_cap_stake


def rolling_win_rate(conn: sqlite3.Connection, lookback: int = 30, min_trades: int = 5) -> float | None:
    rows = conn.execute(
        """
        SELECT pnl_usd FROM positions
        WHERE closed_at IS NOT NULL AND COALESCE(leg_type,'primary')='primary'
          AND COALESCE(exit_reason,'') NOT IN (
            'no_exchange_position','duplicate_merged','netted_on_exchange','simulated_local'
          )
        ORDER BY closed_at DESC LIMIT ?
        """,
        (lookback,),
    ).fetchall()
    if len(rows) < min_trades:
        return None
    wins = sum(1 for r in rows if float(r[0]) > 0)
    return wins / len(rows)


def wr_multiplier(wr: float, baseline: float = 0.55) -> float:
    if baseline <= 0:
        return 1.0
    return max(0.4, min(3.5, wr / baseline))


def compute_stake(
    conn: sqlite3.Connection,
    equity_usd: float,
    confidence: float,
    *,
    open_stakes: list[float] | None = None,
    sl_frac: float | None = None,
) -> float:
    if open_stakes is None:
        open_stakes = []
    deployable = equity_usd * cfg.ACTIVE_CAPITAL_PCT
    used = sum(open_stakes)
    remaining = max(0.0, deployable - used)
    open_n = len(open_stakes)
    if open_n >= cfg.MAX_OPEN or remaining < cfg.MIN_POS_USD:
        return 0.0
    slots_left = max(1, cfg.MAX_OPEN - open_n)
    wr = rolling_win_rate(conn)
    mult = wr_multiplier(wr if wr is not None else 0.55)
    kelly = equity_usd * cfg.KELLY * max(0.15, min(1.0, confidence / 8.0)) * mult
    if cfg.is_scalp():
        from binance_futures_trader.scalp_strategy import scalp_stake_multiplier

        kelly *= scalp_stake_multiplier(confidence) * cfg.SCALP_STAKE_MULT
    base = max(cfg.MIN_POS_USD, min(cfg.MAX_POS_USD, kelly))
    per_slot = remaining / slots_left
    stake = min(remaining, base, per_slot if per_slot >= cfg.MIN_POS_USD else remaining)
    sl = sl_frac if sl_frac is not None and sl_frac > 0 else cfg.SL_PCT
    cap = risk_cap_stake(equity_usd, sl)
    if cap is not None and cap > 0:
        stake = min(stake, cap)
    return max(0.0, round(stake, 2))
