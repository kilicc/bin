"""live.db portföy okuma — yalnızca canlı panel için."""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parent
DATA_DIR = ROOT / "data"
SCANNER_HEARTBEAT_LIVE = DATA_DIR / "polymarket_scanner_live.heartbeat.json"
# Eski tek dosya (paper tarayıcı üzerine yazıyordu) — geriye uyumluluk
SCANNER_HEARTBEAT_LEGACY = DATA_DIR / "polymarket_scanner.heartbeat.json"


def live_db_path() -> Path:
    return Path(os.getenv("LIVE_DB_PATH", str(DATA_DIR / "live.db")))


def read_live_runtime() -> dict[str, Any]:
    """Panel zaman damgası: live.db mtime, son pozisyon, tarayıcı heartbeat."""
    path = live_db_path()
    out: dict[str, Any] = {
        "db_path": path.name,
        "db_exists": path.is_file(),
        "db_mtime": None,
        "last_position_at": None,
        "scanner": None,
    }
    if path.is_file():
        try:
            mtime = path.stat().st_mtime
            out["db_mtime"] = datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()
        except OSError:
            pass
        try:
            conn = sqlite3.connect(str(path))
            row = conn.execute(
                """SELECT MAX(opened_at) FROM positions
                   WHERE closed_at IS NULL AND opened_at IS NOT NULL"""
            ).fetchone()
            conn.close()
            if row and row[0]:
                out["last_position_at"] = str(row[0])
        except sqlite3.Error:
            pass
    try:
        from scanner_runtime import read_heartbeat

        hb = read_heartbeat(SCANNER_HEARTBEAT_LIVE)
        if not hb or hb.get("mode") != "live":
            legacy = read_heartbeat(SCANNER_HEARTBEAT_LEGACY)
            if legacy and legacy.get("mode") == "live":
                hb = legacy
        out["scanner"] = hb
    except Exception:
        for path in (SCANNER_HEARTBEAT_LIVE, SCANNER_HEARTBEAT_LEGACY):
            if path.is_file():
                try:
                    import json

                    raw = json.loads(path.read_text(encoding="utf-8"))
                    if raw.get("mode") == "live":
                        out["scanner"] = raw
                        break
                except Exception:
                    pass
    return out


def read_live_portfolio() -> dict[str, Any]:
    path = live_db_path()
    empty_stats = {
        "realized_pnl": 0.0,
        "closed_trades": 0,
        "wins": 0,
        "win_rate": None,
        "open_trades": 0,
        "avg_edge": None,
    }
    if not path.is_file():
        return {
            "exists": False,
            "db_path": str(path.name),
            "equity": [],
            "timestamps": [],
            "stats": empty_stats,
            "open_positions": [],
            "closed_positions": [],
            "daily_pnl": [],
            "runtime": read_live_runtime(),
        }

    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row

    closed = conn.execute(
        """SELECT id, market_id, question, side, entry_price, true_prob, edge,
                  stake_usd, contracts, opened_at, closed_at, close_price,
                  resolved_yes, pnl_usd, exit_reason, live_order_id
           FROM positions WHERE closed_at IS NOT NULL
           ORDER BY closed_at ASC"""
    ).fetchall()
    _pnl_eps = 1e-4
    closed = [r for r in closed if abs(float(r["pnl_usd"] or 0)) > _pnl_eps]

    open_rows = conn.execute(
        """SELECT id, market_id, question, side, entry_price, true_prob, edge,
                  stake_usd, contracts, opened_at, rationale, outcome_token_id,
                  live_order_id
           FROM positions WHERE closed_at IS NULL
           ORDER BY opened_at DESC"""
    ).fetchall()

    agg = conn.execute(
        """SELECT COUNT(*) n,
                  COALESCE(SUM(CASE WHEN pnl_usd>0 THEN 1 ELSE 0 END),0) wins,
                  COALESCE(SUM(pnl_usd),0) total_pnl
           FROM positions WHERE closed_at IS NOT NULL
             AND ABS(COALESCE(pnl_usd, 0)) > 0.0001"""
    ).fetchone()
    n_closed, wins, total_pnl = int(agg["n"]), int(agg["wins"]), float(agg["total_pnl"])

    ex = conn.execute(
        """SELECT UPPER(COALESCE(exit_reason,'')) er, COUNT(*) c,
                  SUM(CASE WHEN pnl_usd>0 THEN 1 ELSE 0 END) w
           FROM positions WHERE closed_at IS NOT NULL
             AND ABS(COALESCE(pnl_usd, 0)) > 0.0001
           GROUP BY er"""
    ).fetchall()
    tp_n = sl_n = res_n = other_n = 0
    tp_w = sl_w = 0
    for row in ex:
        er, c, w = row["er"] or "", int(row["c"]), int(row["w"])
        if er == "TP":
            tp_n, tp_w = c, w
        elif er == "SL":
            sl_n += c
            sl_w += w
        elif er == "RESOLVED":
            res_n += c
        else:
            other_n += c
    tp_sl_n = tp_n + sl_n
    wr_tp_sl = (tp_w / tp_sl_n) if tp_sl_n > 0 else None

    equity_series: list[float] = []
    timestamps: list[str] = []
    cum = 0.0
    for row in closed:
        pnl = float(row["pnl_usd"] or 0)
        cum += pnl
        timestamps.append(row["closed_at"])
        equity_series.append(round(cum, 4))

    tp_pct = float(os.getenv("TAKE_PROFIT_STAKE_PCT", "0.02"))
    sl_pct = float(os.getenv("STOP_LOSS_STAKE_PCT", "0.02"))
    open_positions = [
        {
            "id": r["id"],
            "market_id": r["market_id"],
            "question": (r["question"] or "")[:90],
            "side": r["side"],
            "entry_price": round(float(r["entry_price"] or 0), 4),
            "true_prob": round(float(r["true_prob"] or r["entry_price"] or 0), 4),
            "edge": round(float(r["edge"] or 0), 4),
            "stake_usd": round(float(r["stake_usd"] or 0), 2),
            "contracts": round(float(r["contracts"] or 0), 4),
            "opened_at": r["opened_at"],
            "live_order_id": r["live_order_id"],
            "tp_target_usd": round(float(r["stake_usd"] or 0) * tp_pct, 4),
            "sl_target_usd": round(float(r["stake_usd"] or 0) * sl_pct, 4),
        }
        for r in open_rows
    ]

    closed_positions = [
        {
            "id": r["id"],
            "question": (r["question"] or "")[:90],
            "side": r["side"],
            "entry_price": round(float(r["entry_price"] or 0), 4),
            "close_price": round(float(r["close_price"] or 0), 4),
            "stake_usd": round(float(r["stake_usd"] or 0), 2),
            "pnl_usd": round(float(r["pnl_usd"] or 0), 4),
            "pnl_pct": round((float(r["pnl_usd"] or 0) / max(float(r["stake_usd"] or 1), 0.01)) * 100, 2),
            "exit_reason": r["exit_reason"],
            "closed_at": r["closed_at"],
        }
        for r in reversed(closed)
    ]

    daily_rows = conn.execute(
        """SELECT DATE(closed_at) d, ROUND(SUM(pnl_usd),4) pnl, COUNT(*) n
           FROM positions WHERE closed_at IS NOT NULL
             AND ABS(COALESCE(pnl_usd, 0)) > 0.0001
           GROUP BY DATE(closed_at) ORDER BY d DESC LIMIT 14"""
    ).fetchall()
    conn.close()

    win_rate = (wins / n_closed) if n_closed > 0 else None
    wr_points: list[dict] = []
    run_w = 0
    for i, row in enumerate(closed):
        pnl = float(row["pnl_usd"] or 0)
        if pnl > 0:
            run_w += 1
        wr_points.append(
            {
                "i": i + 1,
                "wr": round(run_w / (i + 1), 4),
                "win": pnl > 0,
            }
        )

    return {
        "exists": True,
        "db_path": path.name,
        "timestamps": timestamps,
        "equity": equity_series,
        "stats": {
            "realized_pnl": round(total_pnl, 4),
            "closed_trades": n_closed,
            "wins": wins,
            "losses": n_closed - wins,
            "win_rate": round(win_rate, 4) if win_rate is not None else None,
            "wr_tp_sl": round(wr_tp_sl, 4) if wr_tp_sl is not None else None,
            "tp_count": tp_n,
            "sl_count": sl_n,
            "resolved_count": res_n,
            "open_trades": len(open_rows),
        },
        "wr_curve": wr_points,
        "exit_rule": {
            "tp_stake_pct": tp_pct,
            "sl_stake_pct": sl_pct,
            "label": f"TP +{tp_pct*100:.1f}% / SL -{sl_pct*100:.1f}% stake",
        },
        "open_positions": open_positions,
        "closed_positions": closed_positions,
        "daily_pnl": [{"date": r["d"], "pnl": r["pnl"], "n": r["n"]} for r in daily_rows],
        "runtime": read_live_runtime(),
    }
