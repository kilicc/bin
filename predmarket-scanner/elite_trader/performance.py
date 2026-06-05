"""Canlı performans metrikleri — stake ölçekleme için."""
from __future__ import annotations

import os
import sqlite3


def rolling_win_rate(
    conn: sqlite3.Connection,
    *,
    lookback: int | None = None,
    min_trades: int | None = None,
) -> float | None:
    """Son kapanan primary işlemlerden kazanma oranı; yetersiz örnekte None."""
    lb = lookback if lookback is not None else int(os.getenv("ELITE_WR_LOOKBACK", "40"))
    mn = min_trades if min_trades is not None else int(os.getenv("ELITE_WR_MIN_TRADES", "8"))
    rows = conn.execute(
        """
        SELECT pnl_usd FROM positions
        WHERE closed_at IS NOT NULL
          AND COALESCE(leg_type, 'primary') = 'primary'
        ORDER BY closed_at DESC
        LIMIT ?
        """,
        (lb,),
    ).fetchall()
    if len(rows) < mn:
        return None
    wins = sum(1 for r in rows if float(r[0]) > 0)
    return wins / len(rows)
