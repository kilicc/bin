"""SQLite WAL — data/data_lake.db
Yazma kuyruğu: her conn.commit() yerine 2 sn'de bir toplu flush.
Tüm okuma/yazma db_session() ile serileştirilir (macOS segfault önleme).
"""
from __future__ import annotations

import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

_ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = _ROOT / "data" / "data_lake.db"

_lock = threading.RLock()
_conn: sqlite3.Connection | None = None

# --- Yazma kuyruğu -----------------------------------------------------------
_write_queue: list[tuple[str, tuple[Any, ...]]] = []
_write_lock = threading.Lock()
_FLUSH_INTERVAL = 2.0  # sn — yüksek frekanslı commit'i önler


def queue_write(sql: str, params: tuple[Any, ...]) -> None:
    """Yazma işlemini kuyruğa ekle — senkron commit yok."""
    with _write_lock:
        _write_queue.append((sql, params))


def _flush_write_queue() -> None:
    """Kuyruktaki tüm yazmaları tek commit ile db'ye aktar."""
    with _write_lock:
        if not _write_queue:
            return
        batch = list(_write_queue)
        _write_queue.clear()
    with db_session() as conn:
        try:
            for sql, params in batch:
                conn.execute(sql, params)
            conn.commit()
        except Exception:
            pass


def _ensure_conn() -> sqlite3.Connection:
    global _conn
    if _conn is not None:
        try:
            _conn.execute("SELECT 1")
            return _conn
        except sqlite3.Error:
            try:
                _conn.close()
            except Exception:
                pass
            _conn = None
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    _conn = sqlite3.connect(str(DB_PATH), check_same_thread=False, timeout=30.0)
    _conn.row_factory = sqlite3.Row
    _conn.execute("PRAGMA journal_mode=WAL")
    _conn.execute("PRAGMA synchronous=NORMAL")
    _conn.execute("PRAGMA busy_timeout=30000")
    return _conn


@contextmanager
def db_session() -> Iterator[sqlite3.Connection]:
    """Tek global DB kilidi — eşzamanlı okuma/yazma segfault'unu önler."""
    with _lock:
        yield _ensure_conn()


def get_conn() -> sqlite3.Connection:
    """Geriye uyum — yeni kod db_session() kullanmalı."""
    with _lock:
        return _ensure_conn()


def _start_write_flusher() -> None:
    def _loop() -> None:
        while True:
            time.sleep(_FLUSH_INTERVAL)
            try:
                _flush_write_queue()
            except Exception:
                pass

    t = threading.Thread(target=_loop, name="db-write-flusher", daemon=True)
    t.start()


# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS market_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    symbol TEXT,
    price REAL,
    change_pct REAL,
    regime TEXT,
    payload_json TEXT
);

CREATE TABLE IF NOT EXISTS mode_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    mode_id TEXT NOT NULL,
    symbol TEXT,
    side TEXT,
    allowed INTEGER NOT NULL,
    reason TEXT,
    signal_passed INTEGER,
    risk_passed INTEGER,
    execution_passed INTEGER,
    order_sent INTEGER,
    exchange_accepted INTEGER,
    execution_path TEXT,
    payload_json TEXT
);

CREATE TABLE IF NOT EXISTS paper_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_open REAL,
    ts_close REAL,
    mode_id TEXT NOT NULL,
    symbol TEXT,
    side TEXT,
    stake_usd REAL,
    pnl_usd REAL,
    exit_reason TEXT,
    order_sent INTEGER DEFAULT 0,
    payload_json TEXT
);

CREATE TABLE IF NOT EXISTS live_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_open REAL,
    ts_close REAL,
    mode_id TEXT NOT NULL,
    symbol TEXT,
    side TEXT,
    stake_usd REAL,
    pnl_usd REAL,
    exit_reason TEXT,
    order_sent INTEGER DEFAULT 1,
    exchange_accepted INTEGER,
    on_exchange INTEGER,
    payload_json TEXT
);

CREATE TABLE IF NOT EXISTS mode_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    mode_id TEXT NOT NULL,
    trades INTEGER,
    wins INTEGER,
    profit_factor REAL,
    win_rate REAL,
    fee_gross_ratio REAL,
    pnl_per_min REAL,
    top_reject_json TEXT,
    payload_json TEXT
);

CREATE TABLE IF NOT EXISTS evrim_meta_learning (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    cycle INTEGER,
    summary_json TEXT,
    proposals_json TEXT
);

-- Aşama 1 MD: 32 zorunlu log alanı (decision_log)
CREATE TABLE IF NOT EXISTS decision_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    mode_id TEXT NOT NULL,
    mode_name TEXT,
    active_futures_mode TEXT,
    symbol TEXT,
    side TEXT,
    market_regime TEXT,
    score_total REAL,
    score_breakdown TEXT,
    entry_reason TEXT,
    reject_reason TEXT,
    veto_reason TEXT,
    risk_level TEXT,
    expected_net_pnl REAL,
    spread REAL,
    slippage_estimate REAL,
    expected_fee REAL,
    expected_funding REAL,
    order_route TEXT,
    is_paper INTEGER,
    order_sent INTEGER,
    exchange_accepted INTEGER,
    entry_price REAL,
    exit_price REAL,
    gross_pnl REAL,
    fee REAL,
    funding REAL,
    net_pnl REAL,
    hold_time REAL,
    result TEXT,
    learning_tag TEXT,
    payload_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_decision_log_mode_ts ON decision_log(mode_id, ts);
CREATE INDEX IF NOT EXISTS idx_decision_log_ts ON decision_log(ts);
"""


def init_db() -> None:
    with db_session() as conn:
        conn.executescript(_SCHEMA)
        conn.commit()
    _start_write_flusher()
