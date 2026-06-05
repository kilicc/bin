"""Sentinel benchmark + dashboard snapshot — Evrim okuyabilir, profile yazmaz."""
from __future__ import annotations

import json
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
_BENCH = _ROOT / "data" / "sentinel_benchmark.json"
_REJECT_LOG = _ROOT / "data" / "sentinel_reject_log.jsonl"

_decision_count = 0
_last_benchmark_at = 0
_quality_sum = 0.0
_quality_n = 0
_exec_sum = 0.0
_exec_n = 0
_risk_off_count = 0
_reject_reasons: dict[str, int] = defaultdict(int)
_allow_count = 0


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_bench() -> dict[str, Any]:
    if not _BENCH.is_file():
        return {}
    try:
        return json.loads(_BENCH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_bench(data: dict[str, Any]) -> None:
    _BENCH.parent.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = _now_iso()
    _BENCH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _append_reject_log(row: dict[str, Any]) -> None:
    try:
        _REJECT_LOG.parent.mkdir(parents=True, exist_ok=True)
        with _REJECT_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception:
        pass


def on_sentinel_decision(
    signal: dict[str, Any],
    *,
    allowed: bool,
    reason: str,
    meta: dict[str, Any] | None = None,
) -> None:
    global _decision_count, _quality_sum, _quality_n, _exec_sum, _exec_n
    global _risk_off_count, _allow_count

    if reason == "pending":
        return

    meta = meta or signal.get("sentinel_meta") or {}
    _decision_count += 1
    if allowed:
        _allow_count += 1
    else:
        _reject_reasons[str(reason)[:48]] += 1

    qs = meta.get("sentinel_quality_score") or signal.get("sentinel_quality_score")
    if qs is not None:
        _quality_sum += float(qs)
        _quality_n += 1
    ex = meta.get("sentinel_execution_quality_score") or signal.get(
        "sentinel_execution_quality_score"
    )
    if ex is not None:
        _exec_sum += float(ex)
        _exec_n += 1
    if meta.get("sentinel_risk_off"):
        _risk_off_count += 1

    if not allowed:
        _append_reject_log(
            {
                "mode_id": "sentinel",
                "symbol": signal.get("symbol"),
                "timestamp": _now_iso(),
                "change_pct": signal.get("change"),
                "strength": signal.get("strength"),
                "formula_score": signal.get("formula_score"),
                "edge": signal.get("edge"),
                "sentinel_quality_score": qs,
                "sentinel_execution_quality_score": ex,
                "spread_pct": meta.get("spread_pct") or signal.get("spread_pct"),
                "market_regime": signal.get("market_regime") or meta.get("sentinel_regime"),
                "reason": reason,
            }
        )

    if _decision_count % 100 == 0 or (time.time() - _last_benchmark_at) >= 300:
        _write_benchmark_cycle(signal, meta)


def force_benchmark(signal: dict[str, Any], meta: dict[str, Any] | None = None) -> None:
    """Minimum-data / risk-off observation — benchmark without waiting 100 decisions."""
    meta = meta or signal.get("sentinel_meta") or {}
    _write_benchmark_cycle(signal, meta)


def _write_benchmark_cycle(signal: dict[str, Any], meta: dict[str, Any]) -> None:
    global _last_benchmark_at
    _last_benchmark_at = time.time()
    avg_q = _quality_sum / max(_quality_n, 1)
    avg_e = _exec_sum / max(_exec_n, 1)
    safe = float(meta.get("sentinel_safe_market_score") or signal.get("sentinel_safe_market_score") or avg_q)

    bench = {
        "sentinel_benchmark": {
            "sentinel_quality_index": round(avg_q, 2),
            "safe_market_score": round(safe, 2),
            "trend_cleanliness_score": round(min(100.0, avg_q * 0.92), 2),
            "execution_cleanliness_score": round(avg_e, 2),
            "low_risk_symbols": meta.get("low_risk_symbols") or [],
            "high_risk_symbols": meta.get("high_risk_symbols") or [],
            "avoid_market_now": bool(meta.get("avoid_market_now")),
            "recommended_risk_mode": meta.get("recommended_risk_mode") or "normal",
            "best_trend_direction": signal.get("type"),
            "current_market_quality": meta.get("sentinel_quality_tier") or "watch",
            "benchmark_confidence": round(min(0.99, _decision_count / 500.0), 3),
            "decisions_total": _decision_count,
            "allows_total": _allow_count,
            "reject_top": sorted(_reject_reasons.items(), key=lambda x: -x[1])[:8],
        }
    }
    _save_bench(bench)


def get_dashboard(
    *,
    active_futures_mode: str = "",
    live_orders: bool = False,
    book: dict[str, Any] | None = None,
    global_scan_sec: float = 0.5,
) -> dict[str, Any]:
    bench = _load_bench().get("sentinel_benchmark") or {}
    learn = {}
    try:
        from elite_trader.sentinel_learning import snapshot_for_ui

        learn = snapshot_for_ui()
    except Exception:
        pass

    open_p = list((book or {}).get("open") or [])
    closed = list((book or {}).get("closed") or [])
    is_live_route = live_orders and active_futures_mode == "sentinel"

    pnls = [float(c.get("final_pnl") or c.get("net_pnl") or 0) for c in closed]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    wr = len(wins) / max(len(pnls), 1) * 100.0
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    pf = gross_win / gross_loss if gross_loss > 0 else (999.0 if gross_win > 0 else 0.0)

    prof = {}
    try:
        from elite_trader.mode_profiles import get_profile

        prof = get_profile("sentinel") or {}
    except Exception:
        pass

    return {
        "route_mode": "live" if is_live_route else "paper",
        "active_futures_mode": active_futures_mode,
        "paper_trade_count": len(closed),
        "live_trade_count": 0,
        "open_count": len(open_p),
        "sentinel_quality_score_avg": round(_quality_sum / max(_quality_n, 1), 2),
        "safe_market_score": bench.get("safe_market_score"),
        "sentinel_quality_index": bench.get("sentinel_quality_index"),
        "trend_cleanliness_score": bench.get("trend_cleanliness_score"),
        "execution_cleanliness_score": bench.get("execution_cleanliness_score"),
        "paper_pnl": round(sum(pnls), 2),
        "live_pnl": 0.0,
        "pf": round(pf, 3),
        "wr": round(wr, 1),
        "avg_win": round(sum(wins) / max(len(wins), 1), 2),
        "avg_loss": round(sum(losses) / max(len(losses), 1), 2),
        "avg_win_loss_ratio": round(
            (sum(wins) / max(len(wins), 1)) / max(abs(sum(losses) / max(len(losses), 1)), 0.01),
            2,
        ),
        "max_paper_drawdown": learn.get("max_drawdown_observed"),
        "fee_gross": learn.get("fee_gross_quality"),
        "risk_off_count": _risk_off_count,
        "avoid_market_now": bench.get("avoid_market_now", False),
        "recommended_risk_mode": bench.get("recommended_risk_mode", "normal"),
        "sentinel_learning_suggestions": learn,
        "sentinel_benchmark": bench,
        "sentinel_profile_scan_interval_sec": prof.get("scan_interval_sec"),
        "actual_global_scan_interval_sec": global_scan_sec,
        "effective_scan_interval_sec": prof.get("scan_interval_sec")
        if active_futures_mode == "sentinel"
        else global_scan_sec,
        "scan_source": "mode_profile" if active_futures_mode == "sentinel" else "global",
        "reject_top_session": sorted(_reject_reasons.items(), key=lambda x: -x[1])[:8],
    }


def reset_session_stats() -> None:
    global _decision_count, _quality_sum, _quality_n, _exec_sum, _exec_n
    global _risk_off_count, _allow_count, _reject_reasons, _allow_count
    _decision_count = 0
    _quality_sum = _quality_n = _exec_sum = _exec_n = 0
    _risk_off_count = _allow_count = 0
    _reject_reasons = defaultdict(int)
