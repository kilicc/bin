"""9005 — kapanan işlemlerden learned_formula + trade_lessons otomatik yenileme."""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
_APEX_JSON = _ROOT / "data" / "apex_master" / "learned_formula.json"
_LESSONS_JSON = _ROOT / "data" / "elite_9005_trade_lessons.json"

_last_refresh_ts: float = 0.0


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, str(default)))
    except ValueError:
        return default


def _env_int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, str(default)))
    except ValueError:
        return default


def refresh_hours() -> float:
    return _env_float("ELITE_FORMULA_REFRESH_HOURS", 12.0)


def refresh_min_trades() -> int:
    return _env_int("ELITE_FORMULA_REFRESH_MIN_TRADES", 4)


def _pnl(row: dict[str, Any]) -> float:
    return float(row.get("final_pnl") or row.get("net_pnl") or 0)


def _analyze_closed(closed: list[dict[str, Any]]) -> dict[str, Any]:
    if not closed:
        return {
            "trades": 0,
            "win_rate": None,
            "symbol_bias": {},
            "side_weights": {},
            "bad_symbols": [],
            "good_symbols": [],
            "avg_win": 0.0,
            "avg_loss": 0.0,
        }

    sym_stats: dict[str, list[float]] = {}
    side_stats: dict[str, list[float]] = {}
    wins: list[float] = []
    losses: list[float] = []

    for row in closed:
        sym = str(row.get("symbol") or "").upper()
        side = str(row.get("side") or "LONG").upper()
        p = _pnl(row)
        sym_stats.setdefault(sym, []).append(p)
        side_stats.setdefault(side, []).append(p)
        if p > 0:
            wins.append(p)
        elif p < 0:
            losses.append(p)

    def _bias(stats: dict[str, list[float]]) -> dict[str, float]:
        out: dict[str, float] = {}
        for k, pnls in stats.items():
            if not k:
                continue
            wr = sum(1 for x in pnls if x > 0) / len(pnls)
            out[k] = round(0.35 + 0.65 * wr, 3)
        return out

    symbol_bias = _bias(sym_stats)
    side_weights = _bias(side_stats)

    bad: list[str] = []
    good: list[str] = []
    sl_em_counts: dict[str, int] = {}
    for row in closed:
        ex = str(row.get("exit_reason") or "").upper()
        if "SL-EMERGENCY" in ex:
            sym = str(row.get("symbol") or "").upper()
            if sym:
                sl_em_counts[sym] = sl_em_counts.get(sym, 0) + 1
    for sym, pnls in sym_stats.items():
        if sl_em_counts.get(sym, 0) >= 1:
            bad.append(sym)
        if len(pnls) < 2:
            continue
        wr = sum(1 for x in pnls if x > 0) / len(pnls)
        if wr < 0.30:
            bad.append(sym)
        elif wr >= 0.65:
            good.append(sym)
    bad = sorted(set(bad))

    total_wr = sum(1 for r in closed if _pnl(r) > 0) / len(closed)
    return {
        "trades": len(closed),
        "win_rate": round(total_wr, 4),
        "symbol_bias": symbol_bias,
        "side_weights": side_weights,
        "bad_symbols": sorted(bad)[:24],
        "good_symbols": sorted(good, key=lambda s: -symbol_bias.get(s, 0))[:24],
        "avg_win": round(sum(wins) / len(wins), 2) if wins else 0.0,
        "avg_loss": round(sum(losses) / len(losses), 2) if losses else 0.0,
    }


def _tune_thresholds(analysis: dict[str, Any]) -> tuple[float, float]:
    base_edge = _env_float("ELITE_MIN_EDGE", 0.045)
    base_fs = _env_float("ELITE_MIN_FORMULA_SCORE", 0.52)
    wr = analysis.get("win_rate")
    if wr is None:
        return base_edge, base_fs
    if wr < 0.42:
        return base_edge + 0.012, min(0.62, base_fs + 0.04)
    if wr > 0.62:
        return max(0.035, base_edge - 0.008), max(0.46, base_fs - 0.03)
    return base_edge, base_fs


def refresh_formula_from_closed(
    closed: list[dict[str, Any]],
    *,
    force: bool = False,
) -> dict[str, Any] | None:
    """learned_formula.json + elite_9005_trade_lessons.json güncelle."""
    global _last_refresh_ts
    min_n = refresh_min_trades()
    if not force and len(closed) < min_n:
        return None

    analysis = _analyze_closed(closed)
    min_edge, min_fs = _tune_thresholds(analysis)
    now = datetime.now(timezone.utc).isoformat()

    apex: dict[str, Any] = {
        "version": 2,
        "updated_at": now,
        "target_equity_mult": _env_float("ELITE_DAILY_TARGET_MULT", 2.0),
        "target_hours": 24.0,
        "active_capital_pct": _env_float("ELITE_ACTIVE_CAPITAL_PCT", 0.5),
        "min_edge": round(min_edge, 4),
        "min_formula_score": round(min_fs, 4),
        "avg_trader_wr": analysis.get("win_rate") or 0.58,
        "symbol_bias": analysis["symbol_bias"],
        "side_weights": analysis["side_weights"],
        "trades_analyzed": analysis["trades"],
        "good_symbols": analysis["good_symbols"],
        "bad_symbols": analysis["bad_symbols"],
    }

    _APEX_JSON.parent.mkdir(parents=True, exist_ok=True)
    _APEX_JSON.write_text(
        json.dumps(apex, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    lessons: dict[str, Any] = {
        "updated_at": now,
        "trades_count": analysis["trades"],
        "session_win_rate": analysis.get("win_rate"),
        "patterns": {
            "bad_symbols": analysis["bad_symbols"],
            "good_symbols": analysis["good_symbols"],
            "sl_emergency_symbols": sorted(sl_em_counts.keys()),
            "sl_emergency_counts": sl_em_counts,
            "avg_win_net_usd": analysis["avg_win"],
            "avg_loss_net_usd": analysis["avg_loss"],
        },
        "trades": [
            {
                "id": r.get("id"),
                "symbol": r.get("symbol"),
                "side": r.get("side"),
                "final_pnl": _pnl(r),
                "exit_reason": r.get("exit_reason"),
                "stake_usd": r.get("stake_usd"),
            }
            for r in closed[-80:]
        ],
        "apex_thresholds": {
            "min_edge": apex["min_edge"],
            "min_formula_score": apex["min_formula_score"],
        },
    }
    _LESSONS_JSON.write_text(
        json.dumps(lessons, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    try:
        from elite_trader.binance_apex import invalidate_apex_cache

        invalidate_apex_cache()
    except Exception:
        pass

    _last_refresh_ts = time.time()
    print(
        f"  🔄 Apex formül yenilendi: {analysis['trades']} işlem | "
        f"WR={analysis.get('win_rate')} | edge≥{min_edge:.3f} fs≥{min_fs:.2f} | "
        f"iyi={len(analysis['good_symbols'])} kötü={len(analysis['bad_symbols'])}"
    )
    return apex


def maybe_refresh_formula(
    closed: list[dict[str, Any]],
    *,
    force: bool = False,
) -> dict[str, Any] | None:
    """Her N kapanış veya ELITE_FORMULA_REFRESH_HOURS sonra yenile."""
    min_n = refresh_min_trades()
    if len(closed) < min_n and not force:
        return None
    hours = refresh_hours()
    due_time = (
        _last_refresh_ts <= 0
        or (time.time() - _last_refresh_ts) >= hours * 3600.0
    )
    due_count = len(closed) % min_n == 0
    if force or due_time or due_count:
        return refresh_formula_from_closed(closed, force=force)
    return None
