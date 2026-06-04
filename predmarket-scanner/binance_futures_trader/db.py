"""SQLite — binance futures pozisyonları."""
from __future__ import annotations

import sqlite3
from typing import Any
from datetime import datetime, timezone
from pathlib import Path

from binance_futures_trader import config as cfg


def init_db(path: Path | None = None) -> sqlite3.Connection:
    path = path or cfg.DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            coin TEXT NOT NULL,
            side TEXT NOT NULL,
            entry_price REAL NOT NULL,
            stake_usd REAL NOT NULL,
            contracts REAL NOT NULL,
            leverage INTEGER DEFAULT 5,
            tp_frac REAL NOT NULL,
            sl_frac REAL NOT NULL,
            score REAL,
            strategies TEXT,
            opened_at TEXT NOT NULL,
            closed_at TEXT,
            close_price REAL,
            pnl_usd REAL,
            exit_reason TEXT,
            leg_type TEXT DEFAULT 'primary',
            hedge_of_id INTEGER,
            last_price REAL,
            last_update TEXT,
            on_exchange INTEGER DEFAULT 0,
            exchange_order_id TEXT
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_bn_one_open
            ON positions(coin, leg_type) WHERE closed_at IS NULL AND leg_type='primary';
        CREATE TABLE IF NOT EXISTS strategy_stats (
            strategy TEXT PRIMARY KEY,
            wins INTEGER DEFAULT 0,
            losses INTEGER DEFAULT 0,
            total_pnl REAL DEFAULT 0,
            updated_at TEXT
        );
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """
    )
    for col, typ in (
        ("on_exchange", "INTEGER DEFAULT 0"),
        ("exchange_order_id", "TEXT"),
        ("entry_fee_usd", "REAL DEFAULT 0"),
        ("exit_fee_usd", "REAL DEFAULT 0"),
        ("funding_fee_usd", "REAL DEFAULT 0"),
        ("fees_usd", "REAL DEFAULT 0"),
        ("pnl_gross_usd", "REAL"),
        ("open_confidence", "REAL DEFAULT 0"),
        ("runner_mode", "INTEGER DEFAULT 0"),
        ("tp_stage", "INTEGER DEFAULT 0"),
        ("initial_contracts", "REAL"),
        ("realized_partial_usd", "REAL DEFAULT 0"),
    ):
        try:
            conn.execute(f"ALTER TABLE positions ADD COLUMN {col} {typ}")
        except sqlite3.OperationalError:
            pass
    conn.commit()
    try:
        from binance_futures_trader.learner import init_learner_tables

        init_learner_tables(conn)
    except Exception:
        pass
    return conn


def realized_pnl(conn: sqlite3.Connection) -> float:
    r = conn.execute(
        "SELECT COALESCE(SUM(pnl_usd),0) FROM positions WHERE closed_at IS NOT NULL"
    ).fetchone()
    return float(r[0] if r else 0)


def closed_trade_stats_from_rows(
    rows: list[dict[str, Any]] | list[sqlite3.Row],
) -> dict[str, int | float]:
    """Kapanmış pozisyon listesinden win rate (geçmiş tablo ile aynı kaynak)."""
    wins = losses = breakeven = 0
    for r in rows:
        p = dict(r) if not isinstance(r, dict) else r
        raw = p.get("pnl_usd")
        if raw is None:
            raw = p.get("pnl_gross_usd")
        if raw is None:
            continue
        pnl = float(raw)
        if pnl > 0:
            wins += 1
        elif pnl < 0:
            losses += 1
        else:
            breakeven += 1
    total = wins + losses + breakeven
    win_rate = (wins / total * 100.0) if total else 0.0
    return {
        "wins": wins,
        "losses": losses,
        "breakeven": breakeven,
        "total_closed": total,
        "win_rate_pct": round(win_rate, 1),
        "source": "closed_positions",
    }


def closed_trade_stats(conn: sqlite3.Connection) -> dict[str, int | float]:
    """DB'deki tüm kapanmış pozisyonlar (geçmiş tablo sorgusu ile uyumlu)."""
    rows = conn.execute(
        """
        SELECT pnl_usd, pnl_gross_usd, exit_reason, strategies, closed_at
        FROM positions
        WHERE closed_at IS NOT NULL
        ORDER BY closed_at DESC
        """
    ).fetchall()
    out = closed_trade_stats_from_rows(rows)
    out["source"] = "closed_positions"
    return out


def equity(conn: sqlite3.Connection, starting: float | None = None) -> float:
    base = starting if starting is not None else cfg.STARTING_BALANCE
    return base + realized_pnl(conn)


def open_stakes(conn: sqlite3.Connection) -> list[float]:
    return [
        float(r[0])
        for r in conn.execute(
            "SELECT stake_usd FROM positions WHERE closed_at IS NULL"
        ).fetchall()
    ]


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        INSERT INTO meta(key, value, updated_at) VALUES (?,?,?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
        """,
        (key, value, now),
    )
    conn.commit()
