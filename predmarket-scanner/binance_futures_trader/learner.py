"""Kapanış sonrası öğrenme — strateji ağırlıkları, veto, dinamik skor."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from binance_futures_trader import config as cfg

DEFAULT_WEIGHTS = {
    "FUND": 1.0,
    "RSI": 1.0,
    "EMA": 1.0,
    "BB": 1.0,
    "VOL": 1.0,
    "FG": 1.0,
    "MOM": 1.0,
    "MOM3": 1.0,
    "BURST": 1.0,
    "CEX_ARB": 1.0,
    "GAP": 1.0,
    "FLOW": 1.0,
    "NEWS": 1.0,
}

# Senkron / drift kayıtları öğrenmeyi kirletmesin
SKIP_STRATEGIES = frozenset(
    {
        "exchange_sync",
        "sync",
        "",
    }
)


def init_learner_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS trade_lessons (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            position_id INTEGER,
            coin TEXT,
            side TEXT,
            exit_reason TEXT,
            pnl_usd REAL,
            strategies TEXT,
            snapshot_json TEXT,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS strategy_weights (
            strategy TEXT PRIMARY KEY,
            weight REAL DEFAULT 1.0,
            sl_count INTEGER DEFAULT 0,
            tp_count INTEGER DEFAULT 0,
            updated_at TEXT
        );
        """
    )
    for s, w in DEFAULT_WEIGHTS.items():
        conn.execute(
            """
            INSERT INTO strategy_weights(strategy, weight, updated_at)
            VALUES (?,?,?)
            ON CONFLICT(strategy) DO NOTHING
            """,
            (s, w, datetime.now(timezone.utc).isoformat()),
        )
    conn.commit()


def get_weights(conn: sqlite3.Connection) -> dict[str, float]:
    init_learner_tables(conn)
    rows = conn.execute("SELECT strategy, weight FROM strategy_weights").fetchall()
    out = dict(DEFAULT_WEIGHTS)
    for r in rows:
        name = str(r["strategy"])
        if name not in SKIP_STRATEGIES:
            out[name] = float(r["weight"])
    if cfg.EDU_MEMORY_ENABLED:
        try:
            from binance_futures_trader.education_memory import apply_education_to_learner_weights

            out = apply_education_to_learner_weights(out)
        except Exception:
            pass
    return out


def learning_summary(conn: sqlite3.Connection) -> dict:
    """Panel / log için öğrenme özeti."""
    init_learner_tables(conn)
    rows = conn.execute(
        """
        SELECT strategy, weight, sl_count, tp_count FROM strategy_weights
        WHERE strategy NOT IN ('exchange_sync','sync')
        ORDER BY (sl_count + tp_count) DESC, weight DESC
        """
    ).fetchall()
    lessons = conn.execute("SELECT COUNT(*) FROM trade_lessons").fetchone()[0]
    adjusted = [
        {
            "strategy": r["strategy"],
            "weight": round(float(r["weight"]), 3),
            "sl": int(r["sl_count"]),
            "tp": int(r["tp_count"]),
            "wr_pct": round(
                int(r["tp_count"]) / max(1, int(r["sl_count"]) + int(r["tp_count"])) * 100,
                1,
            ),
        }
        for r in rows
        if int(r["sl_count"]) + int(r["tp_count"]) > 0
    ]
    top = sorted(
        [r for r in rows if r["strategy"] not in SKIP_STRATEGIES],
        key=lambda r: float(r["weight"]),
        reverse=True,
    )[:5]
    weak = sorted(
        [r for r in rows if r["strategy"] not in SKIP_STRATEGIES and float(r["weight"]) < 0.9],
        key=lambda r: float(r["weight"]),
    )[:5]
    return {
        "lessons": int(lessons or 0),
        "active_adjustments": len(adjusted),
        "top_weights": [
            {"strategy": r["strategy"], "weight": round(float(r["weight"]), 3)}
            for r in top
        ],
        "weak_weights": [
            {"strategy": r["strategy"], "weight": round(float(r["weight"]), 3)}
            for r in weak
        ],
        "adjusted": adjusted[:12],
    }


def _parse_strategies(strategies: str) -> list[str]:
    out: list[str] = []
    for s in (strategies or "").split(","):
        name = s.strip()
        if name and name not in SKIP_STRATEGIES:
            out.append(name)
    return out


def record_close(
    conn: sqlite3.Connection,
    *,
    position_id: int,
    coin: str,
    side: str,
    exit_reason: str,
    pnl_usd: float,
    strategies: str,
    snapshot: dict,
) -> None:
    init_learner_tables(conn)
    tags = _parse_strategies(strategies)
    if not tags:
        return

    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        INSERT INTO trade_lessons(
            position_id, coin, side, exit_reason, pnl_usd, strategies, snapshot_json, created_at
        ) VALUES (?,?,?,?,?,?,?,?)
        """,
        (
            position_id,
            coin,
            side,
            exit_reason,
            pnl_usd,
            ",".join(tags),
            json.dumps(snapshot, default=str),
            now,
        ),
    )
    won = pnl_usd > 0
    is_loss = pnl_usd < 0
    for strat in tags:
        conn.execute(
            """
            INSERT INTO strategy_weights(strategy, weight, sl_count, tp_count, updated_at)
            VALUES (?,1.0,?,?,?)
            ON CONFLICT(strategy) DO UPDATE SET
              sl_count=sl_count+excluded.sl_count,
              tp_count=tp_count+excluded.tp_count,
              updated_at=excluded.updated_at
            """,
            (
                strat,
                1 if is_loss else 0,
                1 if won else 0,
                now,
            ),
        )
    conn.commit()
    learn_from_outcomes(conn)


def learn_from_outcomes(conn: sqlite3.Connection) -> None:
    """Tüm kapanışlardan (sadece SL değil) ağırlık güncelle."""
    min_trades = cfg.LEARN_MIN_TRADES
    rows = conn.execute(
        """
        SELECT strategy, sl_count, tp_count, weight FROM strategy_weights
        WHERE strategy NOT IN ('exchange_sync','sync')
        AND (sl_count + tp_count) >= ?
        """,
        (min_trades,),
    ).fetchall()
    now = datetime.now(timezone.utc).isoformat()
    for r in rows:
        sl, tp = int(r["sl_count"]), int(r["tp_count"])
        total = sl + tp
        if total < min_trades:
            continue
        wr = tp / total
        w = float(r["weight"])
        if wr < 0.42:
            w = max(cfg.LEARN_WEIGHT_FLOOR, w * 0.90)
        elif wr < 0.50:
            w = max(cfg.LEARN_WEIGHT_FLOOR, w * 0.96)
        elif wr > 0.68:
            w = min(cfg.LEARN_WEIGHT_CAP, w * 1.06)
        elif wr > 0.58:
            w = min(cfg.LEARN_WEIGHT_CAP, w * 1.03)
        conn.execute(
            "UPDATE strategy_weights SET weight=?, updated_at=? WHERE strategy=?",
            (round(w, 4), now, r["strategy"]),
        )
    conn.commit()


def apply_weights(parts: list, weights: dict[str, float]) -> None:
    for p in parts:
        mult = weights.get(p.name, 1.0)
        p.score = round(p.score * mult, 4)


def passes_signal_confirmation(cs) -> bool:
    """En az N bağımsız sinyal parçası aynı yönde."""
    if not cs.parts or not cs.side:
        return False
    direction = 1 if cs.side == "LONG" else -1
    aligned = [
        p
        for p in cs.parts
        if abs(p.score) >= cfg.MIN_SIGNAL_PART_SCORE
        and (p.score > 0) == (direction > 0)
    ]
    families: set[str] = set()
    for p in aligned:
        families.add(p.name.split("_")[0] if "_" in p.name else p.name)
    return len(aligned) >= cfg.MIN_SIGNAL_PARTS and len(families) >= min(
        2, cfg.MIN_SIGNAL_PARTS
    )


def dynamic_min_score(conn: sqlite3.Connection) -> float:
    """Son WR düşükse giriş eşiğini yükselt."""
    base = cfg.MIN_SCORE
    try:
        from binance_futures_trader.capital import rolling_win_rate

        wr = rolling_win_rate(conn, lookback=30)
        if wr is None:
            return base
        if wr < 0.50:
            return base * 1.25
        if wr < 0.58:
            return base * 1.10
        if wr > 0.72:
            return max(base * 0.92, base - 0.15)
    except Exception:
        pass
    return base


def coin_backtest_veto(conn: sqlite3.Connection, coin: str, bt_wr: float) -> bool:
    if bt_wr < cfg.BT_VETO_WR:
        return True
    recent_sl = conn.execute(
        """
        SELECT COUNT(*) FROM trade_lessons
        WHERE coin=? AND pnl_usd < 0
        AND created_at > datetime('now', '-2 days')
        """,
        (coin,),
    ).fetchone()[0]
    return int(recent_sl or 0) >= cfg.COIN_LOSS_VETO_COUNT
