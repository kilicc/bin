"""Sentinel V2 dashboard metrikleri."""
from __future__ import annotations

from typing import Any

from elite_trader.panel_strategy import active_execution_mode, is_live_binance_motor
from elite_trader.sentinel_cooldown import cooldown_stats
from elite_trader.sentinel_learning import snapshot_for_ui


def build_sentinel_health(
    book: dict[str, Any],
    *,
    global_scan_sec: float = 0.5,
) -> dict[str, Any]:
    from elite_trader.sentinel_benchmark import get_dashboard

    exec_mid = active_execution_mode()
    is_live = is_live_binance_motor("sentinel") and exec_mid == "sentinel"
    dash = get_dashboard(
        active_futures_mode=exec_mid,
        live_orders=is_live,
        book=book,
        global_scan_sec=global_scan_sec,
    )

    closed = list(book.get("closed") or [])
    trend_wins = trend_total = 0
    pb_wins = pb_total = 0
    exec_scores: list[float] = []

    for c in closed:
        meta = c.get("sentinel_meta") or {}
        tags = meta.get("sentinel_signal_tags") or []
        if "high_quality_trend" in tags or "ema_continuation" in tags:
            trend_total += 1
            if float(c.get("final_pnl") or c.get("net_pnl") or 0) > 0:
                trend_wins += 1
        if "high_quality_pullback" in tags:
            pb_total += 1
            if float(c.get("final_pnl") or c.get("net_pnl") or 0) > 0:
                pb_wins += 1
        ex = meta.get("sentinel_execution_quality_score") or c.get(
            "sentinel_execution_quality_score"
        )
        if ex is not None:
            exec_scores.append(float(ex))

    learn = snapshot_for_ui()
    cd = cooldown_stats()

    dash["live_trade_count"] = len(closed) if is_live else 0
    dash["paper_trade_count"] = len(closed) if not is_live else dash.get("paper_trade_count", 0)
    dash["trend_alignment_success"] = round(trend_wins / max(1, trend_total), 3)
    dash["pullback_continuation_success"] = round(pb_wins / max(1, pb_total), 3)
    dash["execution_quality_avg"] = round(
        sum(exec_scores) / len(exec_scores), 1
    ) if exec_scores else dash.get("execution_cleanliness_score", 0)
    dash["best_trend_symbols"] = learn.get("best_trend_symbols") or []
    dash["worst_trend_symbols"] = learn.get("worst_trend_symbols") or []
    dash["safest_sessions"] = learn.get("safest_sessions") or []
    dash["cooldown_rejects"] = cd.get("cooldown_rejects", 0)
    dash["profit_factor"] = dash.get("pf")
    dash["win_rate_pct"] = dash.get("wr")
    dash["max_paper_drawdown"] = learn.get("max_drawdown_observed") or dash.get(
        "max_paper_drawdown"
    )
    return dash
