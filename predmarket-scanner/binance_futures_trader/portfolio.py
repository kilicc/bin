"""Pozisyon zenginleştirme ve equity hesabı."""
from __future__ import annotations

import sqlite3
from typing import Any

from binance_futures_trader import config as cfg
from binance_futures_trader.fees import (
    close_fee_breakdown,
    estimate_close_fee,
    estimate_open_fee,
    gross_pnl,
)


def pct_move(side: str, entry: float, cur: float) -> float:
    if entry <= 0 or cur <= 0:
        return 0.0
    if side == "LONG":
        return (cur - entry) / entry
    return (entry - cur) / entry


def unrealized_usd(side: str, entry: float, contracts: float, mark: float) -> float:
    if side == "LONG":
        return contracts * (mark - entry)
    return contracts * (entry - mark)


def tp_sl_prices(side: str, entry: float, tp_frac: float, sl_frac: float) -> tuple[float, float]:
    if side == "LONG":
        return entry * (1 + tp_frac), entry * (1 - sl_frac)
    return entry * (1 - tp_frac), entry * (1 + sl_frac)


def enrich_position(row: dict[str, Any], mark: float | None) -> dict[str, Any]:
    p = dict(row)
    entry = float(p.get("entry_price") or 0)
    side = str(p.get("side") or "LONG")
    contracts = float(p.get("contracts") or 0)
    stake = float(p.get("stake_usd") or 0)
    tpf = float(p.get("tp_frac") or cfg.TP_PCT)
    slf = float(p.get("sl_frac") or cfg.SL_PCT)
    cur = float(mark if mark and mark > 0 else p.get("last_price") or entry)
    move = pct_move(side, entry, cur)
    upnl = unrealized_usd(side, entry, contracts, cur)
    tp_px, sl_px = tp_sl_prices(side, entry, tpf, slf)
    sl_buf = getattr(cfg, "SL_BUFFER_PCT", 0.0)
    sl_trig = slf + sl_buf
    age_sec = 0.0
    try:
        from binance_futures_trader.position_mgmt import position_age_sec

        age_sec = position_age_sec(p.get("opened_at"))
    except Exception:
        pass
    dist_tp = (tpf - move) / tpf * 100 if tpf > 0 else 0
    dist_sl = max(0, (sl_trig + move) / sl_trig * 100) if sl_trig > 0 else 0
    p["mark_price"] = round(cur, 8)
    p["move_pct"] = round(move * 100, 4)
    p["unrealized_pct"] = round((upnl / stake * 100) if stake > 0 else 0, 2)
    p["tp_price"] = round(tp_px, 8)
    p["sl_price"] = round(sl_px, 8)
    p["sl_trigger_pct"] = round(sl_trig * 100, 3)
    p["sl_grace_sec"] = max(0, int(cfg.SL_MIN_HOLD_SEC - age_sec))
    p["dist_to_tp_pct"] = round(max(0, min(100, dist_tp)), 1)
    p["dist_to_sl_pct"] = round(max(0, min(100, dist_sl)), 1)
    p["toward"] = "tp" if move >= 0 else "sl"
    lev = max(1, int(p.get("leverage") or cfg.LEVERAGE_DEFAULT))
    entry_fee = float(p.get("entry_fee_usd") or 0)
    if entry_fee <= 0:
        entry_fee = estimate_open_fee(contracts, entry)
    est_exit_fee = estimate_close_fee(contracts, cur)
    est_fees = entry_fee + est_exit_fee
    p["entry_fee_usd"] = round(entry_fee, 4)
    p["fees_est_usd"] = round(est_fees, 4)
    p["unrealized_gross"] = round(upnl, 4)
    p["unrealized_net"] = round(upnl - est_fees, 4)
    p["unrealized_pnl"] = p["unrealized_net"]
    partial = float(p.get("realized_partial_usd") or 0)
    p["realized_partial_usd"] = round(partial, 4)
    p["total_pnl_live"] = round(partial + p["unrealized_net"], 4)
    runner = int(p.get("runner_mode") or 0) == 1
    p["runner_mode"] = runner
    p["tp_stage"] = int(p.get("tp_stage") or 0)
    p["age_min"] = round(age_sec / 60, 1)
    if runner:
        tiers = cfg.TIER_ROI_PCTS
        p["tp_tiers_pct"] = [round(t * 100, 1) for t in tiers]
        stage = p["tp_stage"]
        p["next_tier_pct"] = (
            round(tiers[stage] * 100, 1) if stage < len(tiers) else None
        )
    elif age_sec >= cfg.STALE_MIN_AGE_SEC:
        p["stale_tp_move_pct"] = round(cfg.STALE_TP_MOVE_PCT * 100, 2)
    p["margin_type"] = cfg.MARGIN_TYPE
    p["leverage"] = lev
    notional = contracts * cur if contracts > 0 and cur > 0 else stake * lev
    if notional > 0:
        p["notional_usd"] = round(notional, 2)
    return p


_EXIT_LABELS: dict[str, str] = {
    "tp": "Take Profit",
    "TP": "Take Profit",
    "STALE_TP": "Uzun süre · TP %2",
    "STALE_TP_ROI": "Uzun süre · ROI %2",
    "TP_TIER_10": "Kademe %10",
    "TP_TIER_20": "Kademe %20",
    "TP_TIER_30": "Kademe %30",
    "RUNNER_CEILING": "Runner tavan",
    "sl": "Stop Loss",
    "signal": "Sinyal",
    "no_exchange_position": "Borsada kapanmış (senkron)",
    "netted_on_exchange": "Netleşme",
    "duplicate_merged": "Çift kayıt birleşti",
    "exchange_sync": "Borsa senkronu",
}


def enrich_closed(row: dict[str, Any]) -> dict[str, Any]:
    p = dict(row)
    entry = float(p.get("entry_price") or 0)
    close = float(p.get("close_price") or 0) or entry
    side = str(p.get("side") or "LONG")
    stake = float(p.get("stake_usd") or 0)
    contracts = float(p.get("contracts") or 0)
    lev = max(1, int(p.get("leverage") or cfg.LEVERAGE_DEFAULT))
    pnl_net = float(p.get("pnl_usd") or 0)
    pnl_gross = float(p.get("pnl_gross_usd") or 0)
    entry_fee = float(p.get("entry_fee_usd") or 0)
    exit_fee = float(p.get("exit_fee_usd") or 0)
    funding_fee = float(p.get("funding_fee_usd") or 0)
    fees_total = float(p.get("fees_usd") or 0)
    if pnl_gross == 0 and entry > 0:
        fb = close_fee_breakdown(
            side=side,
            entry=entry,
            close=close,
            contracts=contracts,
            entry_fee=entry_fee,
            exit_fee=exit_fee,
            funding_fee=funding_fee,
        )
        pnl_gross = fb["pnl_gross_usd"]
        pnl_net = fb["pnl_usd"]
        entry_fee = fb["entry_fee_usd"]
        exit_fee = fb["exit_fee_usd"]
        funding_fee = fb["funding_fee_usd"]
        fees_total = fb["fees_usd"]
    p["pnl_gross_usd"] = round(pnl_gross, 4)
    p["pnl_usd"] = round(pnl_net, 4)
    p["entry_fee_usd"] = round(entry_fee, 4)
    p["exit_fee_usd"] = round(exit_fee, 4)
    p["funding_fee_usd"] = round(funding_fee, 4)
    p["fees_usd"] = round(fees_total, 4)
    p["commission_usd"] = round(entry_fee + exit_fee, 4)
    score = p.get("score")
    strat = str(p.get("strategies") or "")
    move = pct_move(side, entry, close) if entry > 0 and close > 0 else 0.0

    if stake > 0:
        p["pnl_pct"] = round(pnl_net / stake * 100, 2)
    elif entry > 0:
        p["pnl_pct"] = round(move * lev * 100, 2)
    else:
        p["pnl_pct"] = None

    p["move_pct"] = round(move * 100, 3) if entry > 0 else None
    notional = contracts * entry if contracts > 0 and entry > 0 else stake * lev
    p["notional_usd"] = round(notional, 2) if notional > 0 else None
    p["stake_usd"] = round(stake, 2) if stake > 0 else None
    p["tp_pct"] = float(p.get("tp_frac") or cfg.TP_PCT)
    p["sl_pct"] = float(p.get("sl_frac") or cfg.SL_PCT)
    p["on_exchange_label"] = "Borsa" if p.get("on_exchange") else "Yerel"
    reason = str(p.get("exit_reason") or "")
    p["exit_reason_label"] = _EXIT_LABELS.get(reason, reason.replace("_", " ").title() or "—")

    if score is not None and abs(float(score)) < 0.001 and (
        "exchange_sync" in strat or not strat.strip()
    ):
        p["score"] = None
    elif score is not None:
        p["score"] = round(float(score), 2)

    if p.get("close_price") in (None, 0, 0.0) and entry > 0:
        p["close_price"] = entry
    return p


def total_unrealized(rows: list[dict[str, Any]]) -> float:
    return sum(float(r.get("unrealized_pnl") or 0) for r in rows)


def effective_equity(
    conn: sqlite3.Connection,
    exchange_balance: float | None,
    unrealized: float,
) -> float:
    if exchange_balance is not None and exchange_balance > 0:
        return round(exchange_balance, 2)
    from binance_futures_trader.db import equity, realized_pnl

    return round(equity(conn) + unrealized, 2)
