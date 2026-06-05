"""Elite formula paper veritabanı — dashboard ile uyumlu şema."""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from elite_trader.pnl_engine import PnLEngine

ROOT = Path(__file__).resolve().parent.parent

# dashboard.py / momentum_scanner ile aynı çekirdek sütunlar
_DASHBOARD_COLS: tuple[tuple[str, str, str | None], ...] = (
    ("venue", "TEXT", "'polymarket'"),
    ("true_prob", "REAL", None),
    ("rationale", "TEXT", "''"),
    ("resolved_yes", "INTEGER", None),
    ("exit_reason", "TEXT", None),
    ("formula_score", "REAL", None),
    ("formula_version", "INTEGER", None),
    ("condition_id", "TEXT", None),
    ("theme", "TEXT", None),
    ("hours_left_at_entry", "REAL", None),
    ("spread_at_entry", "REAL", None),
    ("yes_price_at_entry", "REAL", None),
    ("yes_price_at_exit", "REAL", None),
    ("score_parts_json", "TEXT", None),
    ("leg_type", "TEXT", "'primary'"),
    ("hedge_of_id", "INTEGER", None),
)


def _sl_stake_pct() -> float:
    try:
        return float(os.getenv("ELITE_SL_STAKE_PCT", "0.025"))
    except ValueError:
        return 0.025


def repair_no_side_pnl(conn: sqlite3.Connection) -> int:
    """NO kapanış PnL — ham unrealized + ELITE_SL_STAKE_PCT tavanı (scanner ile aynı)."""
    fixed = 0
    sl_pct = _sl_stake_pct()
    rows = conn.execute(
        """
        SELECT id, side, entry_price, close_price, contracts, stake_usd, pnl_usd
        FROM positions
        WHERE closed_at IS NOT NULL AND side = 'NO'
          AND close_price IS NOT NULL
        """
    ).fetchall()
    for row in rows:
        entry = float(row["entry_price"])
        close = float(row["close_price"])
        stake = float(row["stake_usd"] or 0)
        contracts = float(row["contracts"] or 0)
        if contracts <= 0 or stake <= 0:
            continue
        raw = round(contracts * (close - entry), 4)
        if raw < 0:
            correct = PnLEngine.cap_sl_pnl(raw, stake, sl_pct)
        else:
            correct = raw
        old = float(row["pnl_usd"] or 0)
        if abs(correct - old) > 0.01:
            conn.execute(
                "UPDATE positions SET pnl_usd=? WHERE id=?",
                (correct, row["id"]),
            )
            fixed += 1
    if fixed:
        conn.commit()
    return fixed


def ensure_dashboard_schema(conn: sqlite3.Connection) -> None:
    """Eski elite_formula.db dosyalarını panel sorgularına uyumlu hale getirir."""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(positions)").fetchall()}
    if not cols:
        return
    for name, typ, default in _DASHBOARD_COLS:
        if name not in cols:
            conn.execute(f"ALTER TABLE positions ADD COLUMN {name} {typ}")
    conn.commit()
    cols = {r[1] for r in conn.execute("PRAGMA table_info(positions)").fetchall()}
    if "true_prob" in cols:
        conn.execute(
            """
            UPDATE positions
            SET true_prob = entry_price
            WHERE true_prob IS NULL
            """
        )
    if "rationale" in cols and "formula_score" in cols:
        conn.execute(
            """
            UPDATE positions
            SET rationale = 'elite score=' || ROUND(formula_score, 3)
            WHERE (rationale IS NULL OR rationale = '')
              AND formula_score IS NOT NULL
            """
        )
    if "venue" in cols:
        conn.execute(
            "UPDATE positions SET venue = 'polymarket' WHERE venue IS NULL OR venue = ''"
        )
    conn.commit()


def record_attribution(
    conn: sqlite3.Connection,
    position_id: int,
    event: str,
    *,
    yes_price: float | None = None,
    unrealized_usd: float | None = None,
    score: float | None = None,
    parts: dict | None = None,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        INSERT INTO trade_attribution
        (position_id, event, yes_price, unrealized_usd, score, parts_json, recorded_at)
        VALUES (?,?,?,?,?,?,?)
        """,
        (
            position_id,
            event,
            yes_price,
            unrealized_usd,
            score,
            json.dumps(parts or {}, ensure_ascii=False),
            now,
        ),
    )
    conn.commit()


def init_db(path: Path | None = None) -> sqlite3.Connection:
    path = path or ROOT / "data" / "elite_formula.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            venue TEXT NOT NULL DEFAULT 'polymarket',
            market_id TEXT NOT NULL,
            question TEXT NOT NULL,
            side TEXT NOT NULL,
            entry_price REAL NOT NULL,
            true_prob REAL NOT NULL,
            edge REAL NOT NULL,
            stake_usd REAL NOT NULL,
            contracts REAL NOT NULL,
            opened_at TEXT NOT NULL,
            closed_at TEXT,
            close_price REAL,
            resolved_yes INTEGER,
            pnl_usd REAL,
            rationale TEXT,
            exit_reason TEXT,
            formula_score REAL,
            formula_version INTEGER,
            condition_id TEXT,
            theme TEXT,
            hours_left_at_entry REAL,
            spread_at_entry REAL,
            yes_price_at_entry REAL,
            yes_price_at_exit REAL,
            score_parts_json TEXT
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_elite_one_open
            ON positions(market_id) WHERE closed_at IS NULL;
        CREATE TABLE IF NOT EXISTS trade_attribution (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            position_id INTEGER NOT NULL,
            event TEXT NOT NULL,
            yes_price REAL,
            unrealized_usd REAL,
            score REAL,
            parts_json TEXT,
            recorded_at TEXT NOT NULL,
            FOREIGN KEY (position_id) REFERENCES positions(id)
        );
        CREATE INDEX IF NOT EXISTS idx_trade_attr_pos
            ON trade_attribution(position_id);
        CREATE TABLE IF NOT EXISTS formula_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """
    )
    ensure_dashboard_schema(conn)
    repair_no_side_pnl(conn)
    conn.commit()
    return conn
