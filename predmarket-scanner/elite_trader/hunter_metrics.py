"""Hunter dashboard metrikleri."""
from __future__ import annotations

from collections import Counter
from typing import Any

from elite_trader.hunter_cooldown import cooldown_stats
from elite_trader.hunter_learning import get_suggestions
from elite_trader.hunter_watchlist import watchlist_size
from elite_trader.panel_strategy import active_execution_mode, is_live_binance_motor


def _pnl(row: dict[str, Any]) -> float:
    return float(row.get("final_pnl") or row.get("net_pnl") or 0)


def hunter_scan_meta() -> dict[str, Any]:
    """Global vs Hunter profil tarama aralığı — dashboard için."""
    import os

    global_iv = float(os.environ.get("ELITE_SCAN_INTERVAL_SEC", 1.0))
    if global_iv <= 0:
        global_iv = 1.0
    ui_tick_iv = max(
        0.15,
        min(2.0, float(os.environ.get("ELITE_UI_TICK_INTERVAL_SEC", 0.35))),
    )
    hunter_iv = 1.0
    trade_top_n = 160
    env_top = max(24, int(os.environ.get("SCAN_EVAL_TOP_N", 48)))
    try:
        from elite_trader.mode_profiles import get_profile

        hp = get_profile("hunter") or {}
        hunter_iv = float(hp.get("scan_interval_sec") or 1.0)
        trade_top_n = int(hp.get("trade_top_n") or 160)
    except Exception:
        pass
    effective_iv = max(0.25, min(global_iv, hunter_iv))
    source = "mode_profile" if hunter_iv < global_iv else "global_cap"
    eval_top = min(max(env_top, trade_top_n), 160)
    return {
        "hunter_profile_scan_interval_sec": hunter_iv,
        "actual_global_scan_interval_sec": global_iv,
        "effective_scan_interval_sec": effective_iv,
        "motor_scan_interval_sec": effective_iv,
        "ui_tick_interval_sec": ui_tick_iv,
        "scan_source": source,
        "scan_eval_top_n": eval_top,
        "hunter_trade_top_n": trade_top_n,
    }


def build_hunter_health(
    book: dict[str, Any],
    *,
    scan_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    open_p = list(book.get("open") or [])
    closed_p = list(book.get("closed") or [])
    exec_mid = active_execution_mode()
    is_live = is_live_binance_motor("hunter") and exec_mid == "hunter"
    route = "live" if is_live else "paper"

    spread_c: Counter[str] = Counter()
    breakout_scores: list[float] = []
    explosive = 0
    liq_opp = 0
    fake_cnt = 0
    sym_pnl: dict[str, float] = {}
    moves: list[float] = []

    for c in closed_p:
        spread_c[str(c.get("spread_risk_level") or "normal")] += 1
        if c.get("breakout_score") is not None:
            breakout_scores.append(float(c["breakout_score"]))
        if c.get("explosive_opportunity"):
            explosive += 1
        if c.get("explosive_liquidation_opportunity"):
            liq_opp += 1
        if float(c.get("fake_breakout_risk") or 0) >= 75:
            fake_cnt += 1
        sym = str(c.get("symbol") or "")
        sym_pnl[sym] = sym_pnl.get(sym, 0.0) + _pnl(c)
        ch = abs(float(c.get("change") or c.get("edge") or 0))
        if ch:
            moves.append(ch)

    wins = [c for c in closed_p if _pnl(c) > 0]
    losses = [c for c in closed_p if _pnl(c) < 0]
    gross = sum(max(0.0, _pnl(c)) for c in closed_p)
    fees = sum(float(c.get("total_fees") or 0) for c in closed_p)
    pf = gross / max(0.01, abs(sum(_pnl(c) for c in losses)))
    avg_win = sum(_pnl(c) for c in wins) / len(wins) if wins else 0.0
    avg_loss = abs(sum(_pnl(c) for c in losses) / len(losses)) if losses else 0.0

    learn = get_suggestions()
    cd = cooldown_stats()
    sm = scan_meta or {}
    try:
        from elite_trader.hunter_benchmark import get_dashboard_extras

        bench = get_dashboard_extras()
    except Exception:
        bench = {}

    return {
        "route_mode": route,
        "active_futures_mode": exec_mid,
        "paper_trade_count": len(closed_p),
        "live_trade_count": 0,
        "breakout_candidates": watchlist_size() + len(open_p),
        "breakout_score_avg": round(
            sum(breakout_scores) / len(breakout_scores), 1
        )
        if breakout_scores
        else 0.0,
        "explosive_opportunity_count": explosive,
        "fake_breakout_rate": round(fake_cnt / max(1, len(closed_p)), 3),
        "liquidation_opportunity_count": liq_opp,
        "liquidation_continuation_rate": learn.get("hunter_learning_suggestions", {}).get(
            "liquidation_continuation_rate", 0
        ),
        "spike_success_rate": learn.get("hunter_learning_suggestions", {}).get(
            "volume_spike_success_rate", 0
        ),
        "avg_move_captured": round(sum(moves) / len(moves), 3) if moves else 0.0,
        "paper_pnl": round(sum(_pnl(c) for c in closed_p), 2),
        "live_pnl": 0.0,
        "profit_factor": round(pf, 3),
        "win_rate_pct": round(len(wins) / max(1, len(closed_p)) * 100, 1),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "avg_win_avg_loss_ratio": round(avg_win / max(0.01, avg_loss), 3),
        "fee_gross_ratio": round(fees / max(0.01, gross), 4) if gross else 0.0,
        "spread_risk_distribution": dict(spread_c),
        "cooldown_rejects": cd.get("cooldown_rejects", 0),
        "fakeout_guard_count": cd.get("fakeout_guard_count", 0),
        "best_breakout_symbols": sorted(sym_pnl, key=sym_pnl.get, reverse=True)[:5],
        "worst_fakeout_symbols": sorted(sym_pnl, key=sym_pnl.get)[:5],
        "hunter_learning_suggestions": learn.get("hunter_learning_suggestions") or {},
        "missed_explosive_moves": bench.get("missed_explosive_moves", 0),
        "reject_top": bench.get("reject_top", []),
        "hunter_profile_scan_interval_sec": sm.get("hunter_profile_scan_interval_sec"),
        "actual_global_scan_interval_sec": sm.get("actual_global_scan_interval_sec"),
        "effective_scan_interval_sec": sm.get("effective_scan_interval_sec"),
        "ui_tick_interval_sec": sm.get("ui_tick_interval_sec"),
        "scan_source": sm.get("scan_source", "global"),
        "open_count": len(open_p),
    }
