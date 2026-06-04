"""Berserk V2 dashboard metrikleri."""
from __future__ import annotations

from collections import Counter
from typing import Any

from elite_trader.berserk_cooldown import cooldown_stats
from elite_trader.berserk_fee_survival import assess_fee_survival, session_snapshot
from elite_trader.berserk_learning import get_suggestions
from elite_trader.berserk_reentry import reentry_stats
from elite_trader.mode_profiles import get_profile
from elite_trader.panel_strategy import active_execution_mode, is_live_binance_motor


def _pnl(row: dict[str, Any]) -> float:
    return float(row.get("final_pnl") or row.get("net_pnl") or 0)


def _duration(row: dict[str, Any]) -> float:
    return float(row.get("duration") or 0)


def build_berserk_health(
    book: dict[str, Any],
    *,
    live_open: list[dict[str, Any]] | None = None,
    live_closed: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    open_p = list(book.get("open") or [])
    closed_p = list(book.get("closed") or [])
    exec_mid = active_execution_mode()
    is_live = is_live_binance_motor("berserk") and exec_mid == "berserk"
    route = "live" if is_live else "paper"
    profile = get_profile("berserk") or {}

    live_open = live_open or []
    live_closed = live_closed or []
    paper_n = len(closed_p)
    live_n = len(live_closed) if is_live else 0

    strength_c: Counter[str] = Counter()
    spread_c: Counter[str] = Counter()
    stake_src_c: Counter[str] = Counter()
    exit_c: Counter[str] = Counter()
    sym_pnl: dict[str, float] = {}
    tag_pnl: dict[str, float] = {}

    for c in closed_p:
        strength_c[str(c.get("signal_strength") or "?")] += 1
        spread_c[str(c.get("spread_risk_level") or "none")] += 1
        stake_src_c[str(c.get("min_stake_source") or "?")] += 1
        r = str(c.get("exit_reason") or "?")
        exit_c[r] += 1
        sym = str(c.get("symbol") or "")
        sym_pnl[sym] = sym_pnl.get(sym, 0.0) + _pnl(c)
        tag = str(c.get("learning_tag") or c.get("signal_strength") or "?")
        tag_pnl[tag] = tag_pnl.get(tag, 0.0) + _pnl(c)

    wins = [c for c in closed_p if _pnl(c) > 0]
    losses = [c for c in closed_p if _pnl(c) < 0]
    gross = sum(max(0.0, _pnl(c)) for c in closed_p)
    fees = sum(float(c.get("total_fees") or 0) for c in closed_p)
    durations = [_duration(c) for c in closed_p if _duration(c) > 0]
    avg_hold = sum(durations) / len(durations) if durations else 0.0
    span_min = max(0.1, sum(durations) / 60.0) if durations else 0.1
    tpm = paper_n / span_min if paper_n else 0.0
    avg_win = sum(_pnl(c) for c in wins) / len(wins) if wins else 0.0
    avg_loss = abs(sum(_pnl(c) for c in losses) / len(losses)) if losses else 0.0
    pf = gross / max(0.01, abs(sum(_pnl(c) for c in losses)))

    best_sym = max(sym_pnl, key=sym_pnl.get) if sym_pnl else None
    worst_sym = min(sym_pnl, key=sym_pnl.get) if sym_pnl else None
    best_tag = max(tag_pnl, key=tag_pnl.get) if tag_pnl else None
    worst_tag = min(tag_pnl, key=tag_pnl.get) if tag_pnl else None

    learn = get_suggestions()
    cd = cooldown_stats()
    reentry = reentry_stats()
    fee_live = assess_fee_survival(profile)
    fee_sess = session_snapshot()

    return {
        "route_mode": route,
        "active_futures_mode": exec_mid,
        "paper_trade_count": paper_n,
        "live_trade_count": live_n,
        "trades_per_min": round(tpm, 3),
        "avg_hold_seconds": round(avg_hold, 1),
        "weak_entry_count": strength_c.get("Weak", 0),
        "medium_entry_count": strength_c.get("Medium", 0),
        "strong_entry_count": strength_c.get("Strong", 0),
        "spread_risk_distribution": dict(spread_c),
        "fee_gross_ratio": fee_live.get("fee_gross_ratio", round(fees / max(0.01, gross), 4) if gross else 0.0),
        "gross_fee_ratio": fee_live.get("gross_fee_ratio", round(gross / max(0.01, fees), 4) if fees else 0.0),
        "profit_factor": round(pf, 3),
        "win_rate_pct": round(len(wins) / paper_n * 100, 1) if paper_n else 0.0,
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "avg_win_avg_loss_ratio": round(avg_win / max(0.01, avg_loss), 3),
        "stale_exit_count": sum(v for k, v in exit_c.items() if "STALE" in k),
        "spike_exit_count": sum(v for k, v in exit_c.items() if "SPIKE" in k),
        "tp_count": exit_c.get("TP", 0),
        "sl_count": exit_c.get("SL", 0),
        "reentry_count": reentry.get("reentry_count", 0),
        "reentry_success_count": reentry.get("reentry_success_count", 0),
        "recovery_mode_active": bool(fee_live.get("recovery_mode")),
        "fee_survival_mode": fee_live.get("fee_survival_mode", "normal"),
        "fee_survival": fee_live,
        "best_micro_signal": best_tag or learn.get("berserk_learning_suggestions", {}).get("best_micro_signal"),
        "worst_micro_signal": worst_tag or learn.get("berserk_learning_suggestions", {}).get("worst_micro_signal"),
        "best_symbols": sorted(sym_pnl, key=sym_pnl.get, reverse=True)[:5],
        "worst_symbols": sorted(sym_pnl, key=sym_pnl.get)[:5],
        "berserk_learning_suggestions": learn.get("berserk_learning_suggestions") or {},
        "cooldown_rejects": cd.get("cooldown_rejects", 0),
        "min_stake_source_distribution": dict(stake_src_c),
        "open_count": len(open_p),
        "paper_pnl": round(sum(_pnl(c) for c in closed_p), 2),
    }
