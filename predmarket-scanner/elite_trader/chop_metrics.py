"""Chop V2 dashboard metrikleri."""
from __future__ import annotations

from collections import Counter
from typing import Any

from elite_trader.chop_cooldown import cooldown_stats
from elite_trader.chop_learning import get_suggestions
from elite_trader.panel_strategy import active_execution_mode, is_live_binance_motor


def _pnl(row: dict[str, Any]) -> float:
    return float(row.get("final_pnl") or row.get("net_pnl") or 0)


def build_chop_health(
    book: dict[str, Any],
) -> dict[str, Any]:
    open_p = list(book.get("open") or [])
    closed_p = list(book.get("closed") or [])
    exec_mid = active_execution_mode()
    is_live = is_live_binance_motor("chop_master") and exec_mid == "chop_master"
    route = "live" if is_live else "paper"

    chop_scores: list[float] = []
    range_widths: list[float] = []
    mr_wins = mr_total = 0
    fb_wins = fb_total = 0
    vwap_wins = vwap_total = 0
    bb_wins = bb_total = 0
    sym_pnl: dict[str, float] = {}
    spread_c: Counter[str] = Counter()

    for c in closed_p:
        spread_c[str(c.get("spread_risk_level") or "normal")] += 1
        sym = str(c.get("symbol") or "")
        sym_pnl[sym] = sym_pnl.get(sym, 0.0) + _pnl(c)
        if c.get("chop_score") is not None:
            chop_scores.append(float(c["chop_score"]))
        if c.get("range_width_pct") is not None:
            range_widths.append(float(c["range_width_pct"]))
        if float(c.get("mean_reversion_score") or 0) >= 65:
            mr_total += 1
            if _pnl(c) > 0:
                mr_wins += 1
        if c.get("failed_breakout_detected"):
            fb_total += 1
            if _pnl(c) > 0:
                fb_wins += 1
        if c.get("vwap_return_success"):
            vwap_total += 1
            if _pnl(c) > 0:
                vwap_wins += 1
        if c.get("bb_rejection_success"):
            bb_total += 1
            if _pnl(c) > 0:
                bb_wins += 1

    wins = [c for c in closed_p if _pnl(c) > 0]
    losses = [c for c in closed_p if _pnl(c) < 0]
    gross = sum(max(0.0, _pnl(c)) for c in closed_p)
    fees = sum(float(c.get("total_fees") or 0) for c in closed_p)
    pf = gross / max(0.01, abs(sum(_pnl(c) for c in losses)))
    avg_win = sum(_pnl(c) for c in wins) / len(wins) if wins else 0.0
    avg_loss = abs(sum(_pnl(c) for c in losses) / len(losses)) if losses else 0.0

    learn = get_suggestions()
    cd = cooldown_stats()
    sug = learn.get("chop_learning_suggestions") or {}

    return {
        "route_mode": route,
        "active_futures_mode": exec_mid,
        "paper_trade_count": len(closed_p) if not is_live else 0,
        "live_trade_count": len(closed_p) if is_live else 0,
        "chop_score_avg": round(sum(chop_scores) / len(chop_scores), 1)
        if chop_scores
        else 0.0,
        "range_width_avg": round(sum(range_widths) / len(range_widths), 4)
        if range_widths
        else 0.0,
        "mean_reversion_success": round(mr_wins / max(1, mr_total), 3),
        "fake_breakout_reversal_success": round(fb_wins / max(1, fb_total), 3),
        "vwap_return_success": round(vwap_wins / max(1, vwap_total), 3),
        "bollinger_rejection_success": round(bb_wins / max(1, bb_total), 3),
        "fee_gross_ratio": round(fees / max(0.01, gross), 4) if gross else 0.0,
        "profit_factor": round(pf, 3),
        "win_rate_pct": round(len(wins) / max(1, len(closed_p)) * 100, 1),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "avg_win_avg_loss_ratio": round(avg_win / max(0.01, avg_loss), 3),
        "best_chop_symbols": sorted(sym_pnl, key=sym_pnl.get, reverse=True)[:5],
        "worst_chop_symbols": sorted(sym_pnl, key=sym_pnl.get)[:5],
        "trend_guard_count": cd.get("trend_guard_count", 0),
        "range_too_narrow_rejects": cd.get("range_too_narrow_rejects", 0),
        "cooldown_rejects": cd.get("cooldown_rejects", 0),
        "paper_pnl": round(sum(_pnl(c) for c in closed_p), 2),
        "spread_risk_distribution": dict(spread_c),
        "chop_learning_suggestions": sug,
        "open_count": len(open_p),
    }
