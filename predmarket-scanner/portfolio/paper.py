"""Paper trading book — SQLite tabanlı, gerçek para YOK.

Amaç:
  - Sinyalleri "alınmış gibi" kaydet.
  - Süre dolunca veya kullanıcı kapatınca P&L hesapla.
  - Equity curve + Brier score raporu üret.

Bilinçli olarak basit tuttum: tek pozisyon, slippage = 1c, fee = 2% (Polymarket).
Gerçek bir backtest motoru için pozisyon yenileme, partial fills, oracle delay
gibi şeyleri eklemen gerekir.
"""
from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from config import settings
from core.edge import EdgeSignal


SCHEMA = """
CREATE TABLE IF NOT EXISTS positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    venue TEXT NOT NULL,
    market_id TEXT NOT NULL,
    question TEXT NOT NULL,
    side TEXT NOT NULL,                -- YES|NO
    entry_price REAL NOT NULL,
    true_prob REAL NOT NULL,
    edge REAL NOT NULL,
    stake_usd REAL NOT NULL,
    contracts REAL NOT NULL,
    opened_at TEXT NOT NULL,
    closed_at TEXT,
    close_price REAL,
    resolved_yes INTEGER,              -- 0|1|NULL
    pnl_usd REAL,
    rationale TEXT
);
CREATE INDEX IF NOT EXISTS idx_positions_open ON positions(market_id, side, closed_at);
"""

FEE_RATE = 0.02      # %2 round-trip simülasyon
SLIPPAGE = 0.01      # +1c slippage on entry


@dataclass
class PaperPosition:
    id: int
    venue: str
    market_id: str
    side: str
    entry_price: float
    contracts: float
    stake_usd: float


class PaperBook:
    def __init__(self, db_path: Optional[Path] = None,
                 starting_balance: Optional[float] = None,
                 max_position_usd: Optional[float] = None):
        self.db_path = db_path or settings.paper_db
        self.starting_balance = starting_balance or settings.paper_starting_balance
        self.max_position_usd = max_position_usd or settings.max_position_usd
        self._conn = sqlite3.connect(self.db_path)
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    # --- Bookkeeping ---------------------------------------------------------

    def _has_open_position(self, market_id: str, side: str) -> bool:
        cur = self._conn.execute(
            "SELECT 1 FROM positions WHERE market_id=? AND side=? AND closed_at IS NULL LIMIT 1",
            (market_id, side),
        )
        return cur.fetchone() is not None

    def equity(self) -> float:
        cur = self._conn.execute(
            "SELECT COALESCE(SUM(pnl_usd), 0) FROM positions WHERE closed_at IS NOT NULL"
        )
        realized = cur.fetchone()[0] or 0.0
        return self.starting_balance + realized

    def open_positions(self) -> list[PaperPosition]:
        cur = self._conn.execute(
            "SELECT id, venue, market_id, side, entry_price, contracts, stake_usd "
            "FROM positions WHERE closed_at IS NULL"
        )
        return [PaperPosition(*row) for row in cur.fetchall()]

    # --- Order placement -----------------------------------------------------

    def maybe_open(self, sig: EdgeSignal) -> Optional[int]:
        """Pozisyon aç (mevcut değilse, ve Kelly>0 ise)."""
        if sig.kelly_sized <= 0:
            return None
        if self._has_open_position(sig.market.market_id, sig.side):
            return None

        equity = self.equity()
        stake = min(equity * sig.kelly_sized, self.max_position_usd)
        if stake < 1.0:
            return None

        # Slippage uygula
        fill_price = min(0.999, sig.market_price + SLIPPAGE)
        contracts = stake / fill_price

        cur = self._conn.execute(
            "INSERT INTO positions "
            "(venue, market_id, question, side, entry_price, true_prob, edge, "
            " stake_usd, contracts, opened_at, rationale) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                sig.market.venue,
                sig.market.market_id,
                sig.market.question,
                sig.side,
                fill_price,
                sig.true_prob,
                sig.edge,
                stake,
                contracts,
                datetime.utcnow().isoformat(),
                sig.rationale,
            ),
        )
        self._conn.commit()
        return cur.lastrowid

    # --- Manual resolution (event happened, mark-to-market) ------------------

    def resolve(self, market_id: str, resolved_yes: bool) -> int:
        """Olay sonucu belli olduğunda çağır. Açık tüm pozisyonları kapatır."""
        closed = 0
        for pos in self.open_positions():
            if pos.market_id != market_id:
                continue
            won = (pos.side == "YES") == resolved_yes
            payout = pos.contracts if won else 0.0
            pnl = payout - pos.stake_usd
            pnl -= pos.stake_usd * FEE_RATE  # fee
            self._conn.execute(
                "UPDATE positions SET closed_at=?, close_price=?, resolved_yes=?, pnl_usd=? "
                "WHERE id=?",
                (datetime.utcnow().isoformat(), 1.0 if won else 0.0,
                 1 if resolved_yes else 0, pnl, pos.id),
            )
            closed += 1
        self._conn.commit()
        return closed

    def mark_to_market(self, market_id: str, current_yes_price: float) -> int:
        """Olay henüz çözmedi ama erken kapatmak istiyorsan kullan."""
        closed = 0
        for pos in self.open_positions():
            if pos.market_id != market_id:
                continue
            close_p = current_yes_price if pos.side == "YES" else (1.0 - current_yes_price)
            payout = pos.contracts * close_p
            pnl = payout - pos.stake_usd - pos.stake_usd * FEE_RATE
            self._conn.execute(
                "UPDATE positions SET closed_at=?, close_price=?, pnl_usd=? WHERE id=?",
                (datetime.utcnow().isoformat(), close_p, pnl, pos.id),
            )
            closed += 1
        self._conn.commit()
        return closed

    # --- Reporting -----------------------------------------------------------

    def report(self) -> dict:
        cur = self._conn.execute(
            "SELECT COUNT(*), "
            " COALESCE(SUM(CASE WHEN pnl_usd>0 THEN 1 ELSE 0 END),0), "
            " COALESCE(SUM(pnl_usd),0) "
            "FROM positions WHERE closed_at IS NOT NULL"
        )
        n, wins, pnl = cur.fetchone()
        open_count = len(self.open_positions())
        return {
            "starting_balance": self.starting_balance,
            "equity": self.equity(),
            "realized_pnl": pnl or 0.0,
            "closed_trades": n,
            "open_trades": open_count,
            "win_rate": (wins / n) if n else None,
        }
