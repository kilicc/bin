"""Sentinel kalite öğrenme önerileri — profile otomatik yazmaz."""
from __future__ import annotations

import json
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
_OUT = _ROOT / "data" / "sentinel_learning_suggestions.json"
_LAST_COUNT = 0


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load() -> dict[str, Any]:
    if not _OUT.is_file():
        return {"suggestions": {}, "updated_at": None}
    try:
        return json.loads(_OUT.read_text(encoding="utf-8"))
    except Exception:
        return {"suggestions": {}, "updated_at": None}


def _save(data: dict[str, Any]) -> None:
    _OUT.parent.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = _now_iso()
    _OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def on_trade_closed(closed: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Her 30 kapanışta öneri üret; mode_profiles.json'a yazmaz."""
    global _LAST_COUNT
    n = len(closed)
    if n < 30 or n - _LAST_COUNT < 30:
        return None
    _LAST_COUNT = n

    wins = [c for c in closed if float(c.get("final_pnl") or c.get("net_pnl") or 0) > 0]
    losses = [c for c in closed if float(c.get("final_pnl") or c.get("net_pnl") or 0) <= 0]
    sym_pnl: dict[str, float] = defaultdict(float)
    sym_n: dict[str, int] = defaultdict(int)
    q_scores: list[float] = []
    fees = 0.0
    gross = 0.0
    max_dd = 0.0
    peak = 0.0
    eq = 0.0

    for c in closed:
        sym = str(c.get("symbol") or "")
        pnl = float(c.get("final_pnl") or c.get("net_pnl") or 0)
        sym_pnl[sym] += pnl
        sym_n[sym] += 1
        fees += float(c.get("total_fees") or 0)
        gross += abs(pnl)
        eq += pnl
        peak = max(peak, eq)
        max_dd = min(max_dd, eq - peak)
        meta = c.get("sentinel_meta") or {}
        if meta.get("sentinel_quality_score") is not None:
            q_scores.append(float(meta["sentinel_quality_score"]))

    best_syms = sorted(sym_pnl.items(), key=lambda x: -x[1])[:5]
    worst_syms = sorted(sym_pnl.items(), key=lambda x: x[1])[:5]
    wr = len(wins) / max(len(closed), 1)
    avg_q = sum(q_scores) / len(q_scores) if q_scores else 62.0

    suggestions = {
        "quality_signal_rank": sorted(
            [{"symbol": s, "pnl": round(p, 2), "n": sym_n[s]} for s, p in sym_pnl.items()],
            key=lambda x: -x["pnl"],
        )[:12],
        "best_trend_symbols": [s for s, _ in best_syms if sym_pnl[s] > 0],
        "worst_trend_symbols": [s for s, _ in worst_syms if sym_pnl[s] < 0],
        "safest_sessions": [],
        "recommended_min_quality_score": round(max(58.0, min(72.0, avg_q - 2)), 1),
        "recommended_min_edge": 0.12,
        "recommended_min_formula_score": 0.60,
        "recommended_execution_threshold": 70,
        "recommended_spread_limit": 0.12,
        "best_pullback_pattern": "high_quality_pullback",
        "worst_pullback_pattern": "sentinel_chop_risk",
        "sentinel_benchmark_score": round(wr * 100, 1),
        "max_drawdown_observed": round(max_dd, 2),
        "fee_gross_quality": round(fees / max(gross, 1.0), 4),
        "confidence": round(min(0.95, len(closed) / 120.0), 3),
        "trades_analyzed": len(closed),
    }

    payload = {"sentinel_learning_suggestions": suggestions, "updated_at": _now_iso()}
    _save(payload)
    return suggestions


def snapshot_for_ui() -> dict[str, Any]:
    return _load().get("sentinel_learning_suggestions") or {}
