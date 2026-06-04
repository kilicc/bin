#!/usr/bin/env python3
"""Evrim hybrid + MTF backtest — restart gerektirmez; state dosyalarini gunceller."""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=False)
load_dotenv(ROOT / "scenarios" / "binance_elite_8300_9005.env", override=True)
os.environ.setdefault("BN_FUT_MODE", "main")
os.environ["BINANCE_AUTH_QUICK"] = "1"

DAYS = int(os.getenv("EVRIM_BT_DAYS", "5"))
MAX_SYMBOLS = int(os.getenv("EVRIM_BT_MAX_SYMBOLS", "14"))
LOOKBACK = 10
MOM_THRESH = 0.12
TP_PCT = 0.006
SL_PCT = 0.0025
TP_TRIG = 0.98

SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
    "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "LTCUSDT",
    "NEARUSDT", "APTUSDT", "ARBUSDT", "OPUSDT",
]


def _strength(ch: float) -> str:
    a = abs(ch)
    if a > 0.5:
        return "Strong"
    if a > 0.25:
        return "Medium"
    return "Weak"


def _build_bt_ctx(candles: list[dict], idx: int, sym: str = "") -> dict[str, Any]:
    slice_c = candles[max(0, idx - 34) : idx + 1]
    if len(slice_c) < 8:
        return {"ok": False}
    closes = [float(x["c"]) for x in slice_c]
    vols = [float(x.get("v", 0)) for x in slice_c]
    vol_now = vols[-1]
    vol_avg = sum(vols[-20:]) / max(1, min(20, len(vols)))
    vol_ratio = vol_now / vol_avg if vol_avg > 0 else 1.0
    last3 = closes[-3:]
    up3 = len(last3) >= 3 and last3[0] < last3[1] < last3[2]
    down3 = len(last3) >= 3 and last3[0] > last3[1] > last3[2]
    last = slice_c[-1]
    hi, lo, cl = float(last["h"]), float(last["l"]), float(last["c"])
    atr_pct = (hi - lo) / max(cl, 1e-12) * 100
    rng5 = max(closes[-5:]) - min(closes[-5:])
    flat = rng5 / max(cl, 1e-12) * 100 < 0.25
    chop_flag = flat and vol_ratio < 1.1
    breakout_flag = vol_ratio >= 1.2 and atr_pct >= 0.12
    spread_pct = 0.05 if vol_ratio < 2.0 else 0.18
    liq_proxy = vol_ratio >= 2.5 and atr_pct >= 0.15
    return {
        "ok": True,
        "symbol": sym,
        "radar_bt_proxy": True,
        "vo_backtest_proxy": True,
        "liquidation_proxy": liq_proxy,
        "vo": {"slippage_est_bps": 8 if spread_pct < 0.12 else 32},
        "vol_ratio": round(vol_ratio, 3),
        "atr_pct": round(atr_pct, 4),
        "spread_pct": spread_pct,
        "funding_abs": 0,
        "ema_trend": "up" if closes[-1] > closes[-5] else "down",
        "direction_3": "up" if up3 else "down" if down3 else "none",
        "regime": "mixed",
        "btc_regime": "unknown",
        "chop": chop_flag,
        "chop_flag": chop_flag,
        "breakout_flag": breakout_flag,
        "price": closes[-1],
        "klines_5m": [
            {
                "o": float(x.get("o", 0)),
                "h": float(x.get("h", 0)),
                "l": float(x.get("l", 0)),
                "c": float(x.get("c", 0)),
                "v": float(x.get("v", 0)),
            }
            for x in slice_c
        ],
        "last_candle": {
            "o": float(last.get("o", 0)),
            "h": float(last.get("h", 0)),
            "l": float(last.get("l", 0)),
            "c": float(last.get("c", 0)),
        },
    }


def backtest_symbol(candles: list[dict], profile: dict, sym: str) -> dict:
    from elite_trader.evrim_hybrid_scorer import evaluate

    if len(candles) < LOOKBACK + 50:
        return {"trades": 0, "signals": 0, "entered": 0}

    wins = losses = entered = signals = 0
    score_sum = pa_score_sum = 0.0
    chop_n = pa_veto_n = fake_n = spread_veto_n = slippage_red_n = 0
    rel_vol_sum = 0.0
    regime_counts: dict[str, int] = {}
    regime_wins: dict[str, int] = {}
    regime_trades: dict[str, int] = {}
    regime_veto_n = chop_skip_n = radar_veto_n = opp_enter_n = 0
    dyn_tp_sum = dyn_sl_sum = 0.0
    partial_n = momentum_exit_n = expectancy_veto_n = 0
    pattern_wins: dict[str, int] = {}
    pattern_trades: dict[str, int] = {}
    i = LOOKBACK
    while i < len(candles) - 8:
        window = candles[i - LOOKBACK : i]
        price = float(candles[i]["c"])
        old = float(window[0]["c"])
        change = ((price - old) / old) * 100 if old else 0.0
        if abs(change) <= MOM_THRESH:
            i += 1
            continue
        side = "LONG" if change > 0 else "SHORT"
        sig = {
            "symbol": sym,
            "type": side,
            "change": change,
            "strength": _strength(change),
        }
        bt_ctx = _build_bt_ctx(candles, i, sym)
        bt_profile = dict(profile)
        bt_profile["evrim_expectancy_min_net_usd"] = 0.0
        bt_profile["evrim_expectancy_bt_simulation"] = True
        dec = evaluate(sig, bt_profile, log_decision=False, ctx_override=bt_ctx)
        signals += 1
        pa = (dec.context or {}).get("pa") or {}
        vo = (dec.context or {}).get("vo") or {}
        regime_id = str((dec.context or {}).get("market_regime") or "chop")
        regime_counts[regime_id] = regime_counts.get(regime_id, 0) + 1
        pol = (dec.context or {}).get("regime_policy") or {}
        if dec.hard_veto == "spread_wide":
            spread_veto_n += 1
        if dec.hard_veto == "fake_breakout":
            pa_veto_n += 1
        if dec.hard_veto and str(dec.hard_veto).startswith("regime_"):
            regime_veto_n += 1
            if regime_id == "chop":
                chop_skip_n += 1
        radar = (dec.context or {}).get("market_radar") or {}
        if dec.hard_veto and (
            str(dec.hard_veto).startswith("spread_halt")
            or str(dec.hard_veto).startswith("api_slow")
            or str(dec.hard_veto).startswith("dd_halt")
            or str(dec.hard_veto).startswith("uncertain")
            or "radar" in str(dec.hard_veto)
        ):
            radar_veto_n += 1
        if dec.hard_veto in ("negative_expectancy",) or (
            dec.reason_skip and "fee_protection" in str(dec.reason_skip)
        ):
            expectancy_veto_n += 1
        if float(pa.get("fake_breakout_prob") or 0) >= 0.55:
            fake_n += 1
        if dec.chop_mode:
            chop_n += 1
        if not dec.ok:
            i += 1
            continue
        entered += 1
        if radar.get("opportunity_mode"):
            opp_enter_n += 1
        score_sum += dec.total_score
        pa_score_sum += float(pa.get("aligned_score") or 0)
        rel_vol_sum += float(vo.get("rel_volume") or bt_ctx.get("vol_ratio") or 0)
        if float(vo.get("stake_mult") or 1) < 0.95:
            slippage_red_n += 1
        detected = pa.get("detected") or []
        top_pat = detected[0] if detected else None
        entry = float(candles[i + 1]["o"])
        if entry <= 0:
            i += 1
            continue
        from elite_trader.evrim_dynamic_exit import compute_dynamic_exit, simulate_bt_exit

        dyn_plan = compute_dynamic_exit(
            total_score=float(dec.total_score or 70),
            side=side,
            signal=sig,
            ctx=dec.context or bt_ctx,
            profile=profile,
        )
        win_trade, partial_hit, exit_tag = simulate_bt_exit(
            side=side,
            entry=entry,
            candles=candles,
            start_idx=i + 2,
            plan=dyn_plan,
        )
        dyn_tp_sum += dyn_plan.tp_stake_pct
        dyn_sl_sum += dyn_plan.sl_stake_pct
        if partial_hit:
            partial_n += 1
        if exit_tag == "MOMENTUM-FADE":
            momentum_exit_n += 1
        try:
            from elite_trader.evrim_trade_learning import record_trade_from_backtest
            from elite_trader.fee_economics import round_trip_fee_usd

            stake_est = float(profile.get("min_stake_usd") or 140)
            lev = 7
            fees = round_trip_fee_usd(stake_est, lev)
            exit_px = float(candles[min(i + 79, len(candles) - 1)]["c"])
            record_trade_from_backtest(
                symbol=sym,
                side=side,
                entry=entry,
                exit_px=exit_px,
                win=win_trade,
                exit_tag=exit_tag,
                dec_context=dec.context or bt_ctx,
                dec_components=dec.components or {},
                total_score=float(dec.total_score or 0),
                regime_id=regime_id,
                profile=profile,
                stake_est=stake_est,
                fees=fees,
                mfe=stake_est * dyn_plan.tp_stake_pct if win_trade else 0.0,
                mae=-stake_est * dyn_plan.sl_stake_pct if not win_trade else 0.0,
            )
        except Exception:
            pass
        if win_trade:
            wins += 1
            regime_wins[regime_id] = regime_wins.get(regime_id, 0) + 1
            if top_pat:
                pattern_wins[top_pat] = pattern_wins.get(top_pat, 0) + 1
        else:
            losses += 1
        regime_trades[regime_id] = regime_trades.get(regime_id, 0) + 1
        if top_pat:
            pattern_trades[top_pat] = pattern_trades.get(top_pat, 0) + 1
        i += 1

    trades = wins + losses
    pattern_wr = {
        k: round(pattern_wins.get(k, 0) / pattern_trades[k] * 100, 1)
        for k in pattern_trades
        if pattern_trades[k] > 0
    }
    return {
        "trades": trades,
        "wins": wins,
        "win_rate": round(wins / trades * 100, 1) if trades else 0,
        "signals": signals,
        "entered": entered,
        "enter_rate": round(entered / signals * 100, 1) if signals else 0,
        "avg_score_entered": round(score_sum / entered, 1) if entered else 0,
        "avg_pa_score_entered": round(pa_score_sum / entered, 1) if entered else 0,
        "chop_rate": round(chop_n / signals * 100, 1) if signals else 0,
        "pa_veto_count": pa_veto_n,
        "fake_breakout_signals": fake_n,
        "spread_veto_count": spread_veto_n,
        "slippage_stake_reduces": slippage_red_n,
        "avg_rel_vol_entered": round(rel_vol_sum / entered, 2) if entered else 0,
        "pattern_wr": pattern_wr,
        "regime_counts": regime_counts,
        "regime_wins": regime_wins,
        "regime_trades": regime_trades,
        "regime_wr": {
            rid: round(regime_wins.get(rid, 0) / regime_trades[rid] * 100, 1)
            for rid in regime_trades
            if regime_trades[rid] > 0
        },
        "regime_enter_rate": round(entered / signals * 100, 1) if signals else 0,
        "regime_veto_count": regime_veto_n,
        "chop_skip_count": chop_skip_n,
        "avg_dyn_tp_pct": round(dyn_tp_sum / entered * 100, 3) if entered else 0,
        "avg_dyn_sl_pct": round(dyn_sl_sum / entered * 100, 3) if entered else 0,
        "partial_tp_count": partial_n,
        "momentum_exit_count": momentum_exit_n,
        "expectancy_veto_count": expectancy_veto_n,
        "radar_veto_count": radar_veto_n,
        "opportunity_enter_count": opp_enter_n,
    }


def main() -> None:
    from binance_futures_trader.client import BinanceFuturesClient
    from elite_trader.evrim_training import (
        apply_backtest_results,
        ensure_mtf_prompt_ingested,
        ensure_pa_prompt_ingested,
        ensure_vo_prompt_ingested,
        ensure_regime_prompt_ingested,
        ensure_dynamic_exit_prompt_ingested,
        ensure_expectancy_prompt_ingested,
        ensure_trade_learning_prompt_ingested,
        ensure_param_auto_test_prompt_ingested,
        ensure_market_radar_prompt_ingested,
    )
    from elite_trader.evrim_expectancy import (
        _default_metrics,
        metrics_snapshot,
        save_expectancy_metrics,
    )
    from elite_trader.mode_profiles import get_profile

    print("Evrim hybrid backtest — full stack + trade learning")
    save_expectancy_metrics(_default_metrics())
    ensure_mtf_prompt_ingested()
    ensure_pa_prompt_ingested()
    ensure_vo_prompt_ingested()
    ensure_regime_prompt_ingested()
    ensure_dynamic_exit_prompt_ingested()
    ensure_expectancy_prompt_ingested()
    ensure_trade_learning_prompt_ingested()
    ensure_param_auto_test_prompt_ingested()
    ensure_market_radar_prompt_ingested()
    profile = get_profile("evrim") or {}
    client = BinanceFuturesClient()

    results: list[dict] = []
    for sym in SYMBOLS[:MAX_SYMBOLS]:
        coin = sym.replace("USDT", "")
        print(f"  … {sym}", flush=True)
        try:
            candles = client.klines_history(coin, "5m", days=DAYS) or []
        except Exception as exc:
            results.append({"symbol": sym, "error": str(exc)[:80]})
            continue
        r = backtest_symbol(candles, profile, sym)
        r["symbol"] = sym
        results.append(r)
        print(
            f"    {sym}: sig={r.get('signals', 0)} enter={r.get('entered', 0)} "
            f"WR={r.get('win_rate', 0)}% avgSc={r.get('avg_score_entered', 0)}"
        )

    total_trades = sum(r.get("trades", 0) for r in results)
    total_wins = sum(r.get("wins", 0) for r in results)
    total_signals = sum(r.get("signals", 0) for r in results)
    total_entered = sum(r.get("entered", 0) for r in results)
    wr = round(total_wins / total_trades * 100, 1) if total_trades else 0
    avg_chop = (
        sum(r.get("chop_rate", 0) for r in results) / len(results) if results else 0
    )
    total_pa_veto = sum(r.get("pa_veto_count", 0) for r in results)
    total_fake_sig = sum(r.get("fake_breakout_signals", 0) for r in results)
    fake_rate = (
        round(total_fake_sig / total_signals * 100, 1) if total_signals else 0
    )
    pa_veto_rate = (
        round(total_pa_veto / total_signals * 100, 1) if total_signals else 0
    )
    total_spread_veto = sum(r.get("spread_veto_count", 0) for r in results)
    total_regime_veto = sum(r.get("regime_veto_count", 0) for r in results)
    total_expectancy_veto = sum(r.get("expectancy_veto_count", 0) for r in results)
    total_radar_veto = sum(r.get("radar_veto_count", 0) for r in results)
    total_opp_enter = sum(r.get("opportunity_enter_count", 0) for r in results)
    total_partial = sum(r.get("partial_tp_count", 0) for r in results)
    total_mom_exit = sum(r.get("momentum_exit_count", 0) for r in results)
    avg_dyn_tp = (
        round(
            sum(r.get("avg_dyn_tp_pct", 0) * r.get("entered", 0) for r in results)
            / max(1, total_entered),
            3,
        )
        if total_entered
        else 0
    )
    avg_dyn_sl = (
        round(
            sum(r.get("avg_dyn_sl_pct", 0) * r.get("entered", 0) for r in results)
            / max(1, total_entered),
            3,
        )
        if total_entered
        else 0
    )
    regime_counts_all: dict[str, int] = {}
    regime_wins_all: dict[str, int] = {}
    regime_trades_all: dict[str, int] = {}
    for r in results:
        for rid, c in (r.get("regime_counts") or {}).items():
            regime_counts_all[rid] = regime_counts_all.get(rid, 0) + int(c)
        for rid, w in (r.get("regime_wins") or {}).items():
            regime_wins_all[rid] = regime_wins_all.get(rid, 0) + int(w)
        for rid, t in (r.get("regime_trades") or {}).items():
            regime_trades_all[rid] = regime_trades_all.get(rid, 0) + int(t)
    regime_wr = {
        rid: round(regime_wins_all.get(rid, 0) / max(1, regime_trades_all.get(rid, 1)) * 100, 1)
        for rid in set(regime_counts_all) | set(regime_trades_all)
    }
    dominant_regime = (
        max(regime_counts_all, key=regime_counts_all.get)
        if regime_counts_all
        else "chop"
    )
    spread_veto_rate = (
        round(total_spread_veto / total_signals * 100, 1) if total_signals else 0
    )
    avg_rel_vol_entered = (
        round(
            sum(r.get("avg_rel_vol_entered", 0) * r.get("entered", 0) for r in results)
            / max(1, total_entered),
            2,
        )
        if total_entered
        else 0
    )

    cur_min = int(profile.get("evrim_min_total_score") or 55)
    new_min = cur_min
    if wr < 48 and total_trades >= 20:
        new_min = min(68, cur_min + 1)
    elif wr > 58 and total_trades >= 30:
        new_min = max(52, cur_min - 1)

    weights = {
        "trend_alignment": 1.0 if wr >= 50 else 0.9,
        "macd": 1.05 if wr >= 52 else 1.0,
        "bollinger": 1.0,
        "vwap": 1.0,
        "rsi_penalty": 1.1 if wr < 50 else 1.0,
    }
    pa_weights = {
        "breakout": 0.9 if wr < 48 else 1.05,
        "fake_breakout": 1.1 if fake_rate > 25 else 1.0,
        "micro_hh_hl": 1.05 if wr >= 50 else 1.0,
        "micro_ll_lh": 1.05 if wr >= 50 else 1.0,
        "momentum_candle": 1.0,
        "engulfing": 1.05 if wr >= 52 else 1.0,
        "volume_breakout": 1.05 if wr >= 50 else 0.95,
        "volume_breakdown": 1.05 if wr >= 50 else 0.95,
        "strong_close_long": 1.0,
        "strong_close_short": 1.0,
    }
    veto_thresh = float(profile.get("evrim_pa_fake_veto_threshold") or 0.72)
    if fake_rate > 30:
        veto_thresh = max(0.60, veto_thresh - 0.03)

    spread_veto_pct = float(profile.get("evrim_vo_spread_veto_pct") or 0.12)
    if spread_veto_rate > 5:
        spread_veto_pct = max(0.08, spread_veto_pct - 0.01)

    regime_overrides: dict[str, dict[str, float]] = {}
    if regime_wr.get("chop", 100) < 45:
        regime_overrides["chop"] = {"min_score_delta": 5, "stake_mult": 0.5}
    if regime_wr.get("trending", 0) > 52:
        regime_overrides["trending"] = {"tp_mult": 1.18}

    exp_metrics = metrics_snapshot()
    expectancy_overrides: dict[str, float] = {}
    fee_gross = float(exp_metrics.get("fee_to_gross_profit_pct") or 0)
    if fee_gross >= 70:
        expectancy_overrides = {"stake_mult": 0.7, "min_score_delta": 2}
    elif fee_gross >= 45:
        expectancy_overrides = {"stake_mult": 0.85, "min_score_delta": 1}

    dynamic_exit_overrides: dict[str, float] = {}
    if wr < 45 and total_trades >= 15:
        dynamic_exit_overrides["tp_mult"] = 0.92
        dynamic_exit_overrides["sl_mult"] = 1.05
    elif wr > 55 and total_trades >= 20:
        dynamic_exit_overrides["tp_mult"] = 1.06

    vo_weights = {
        "relative_volume": 1.05 if avg_rel_vol_entered >= 1.2 else 1.0,
        "volume_spike": 1.05 if avg_rel_vol_entered >= 1.5 else 1.0,
        "buy_sell_imbalance": 1.05 if wr >= 50 else 0.95,
        "orderbook_sweep": 1.0,
        "aggressive_market_buy": 1.05 if wr >= 52 else 1.0,
        "aggressive_market_sell": 1.05 if wr >= 52 else 1.0,
    }

    summary = {
        "at": datetime.now(timezone.utc).isoformat(),
        "days": DAYS,
        "symbols_n": len(results),
        "total_signals": total_signals,
        "total_entered": total_entered,
        "enter_rate_pct": round(total_entered / total_signals * 100, 1)
        if total_signals
        else 0,
        "total_trades": total_trades,
        "total_wins": total_wins,
        "win_rate_pct": wr,
        "avg_chop_rate_pct": round(avg_chop, 1),
        "pa_veto_count": total_pa_veto,
        "pa_veto_rate_pct": pa_veto_rate,
        "fake_breakout_rate_pct": fake_rate,
        "spread_veto_count": total_spread_veto,
        "spread_veto_rate_pct": spread_veto_rate,
        "regime_veto_count": total_regime_veto,
        "regime_veto_rate_pct": (
            round(total_regime_veto / total_signals * 100, 1) if total_signals else 0
        ),
        "regime_counts": regime_counts_all,
        "regime_wr": regime_wr,
        "dominant_regime": dominant_regime,
        "avg_rel_vol_entered": avg_rel_vol_entered,
        "evrim_vo_spread_veto_pct": round(spread_veto_pct, 3),
        "evrim_min_total_score": new_min,
        "evrim_max_tier": "max_aggressive" if wr >= 55 else "aggressive",
        "evrim_pa_fake_veto_threshold": round(veto_thresh, 2),
        "indicator_weights": weights,
        "pa_weights": pa_weights,
        "vo_weights": vo_weights,
        "regime_stats": regime_wr,
        "regime_overrides": regime_overrides,
        "dynamic_exit_stats": {
            "avg_tp_pct_entered": avg_dyn_tp,
            "avg_sl_pct_entered": avg_dyn_sl,
            "partial_tp_count": total_partial,
            "momentum_exit_count": total_mom_exit,
            "win_rate_pct": wr,
        },
        "dynamic_exit_overrides": dynamic_exit_overrides,
        "expectancy_veto_count": total_expectancy_veto,
        "expectancy_veto_rate_pct": (
            round(total_expectancy_veto / total_signals * 100, 1) if total_signals else 0
        ),
        "expectancy_metrics": exp_metrics,
        "expectancy_overrides": expectancy_overrides,
        "radar_veto_count": total_radar_veto,
        "radar_veto_rate_pct": (
            round(total_radar_veto / total_signals * 100, 1) if total_signals else 0
        ),
        "opportunity_enter_count": total_opp_enter,
        "radar_stats": {
            "veto_count": total_radar_veto,
            "opportunity_enter_count": total_opp_enter,
            "opportunity_rate_pct": (
                round(total_opp_enter / total_entered * 100, 1) if total_entered else 0
            ),
        },
        "per_symbol": results,
    }

    try:
        from elite_trader.evrim_trade_learning import load_recent_trades, run_periodic_analysis

        la = run_periodic_analysis(50)
        summary["learning_analysis"] = la.get("analysis")
        summary["pending_parameter_patch"] = la.get("pending_patch") or {}
        summary["pending_patch_requires_backtest"] = True
        summary["trade_journal_bt_n"] = len(load_recent_trades(5000))
    except Exception as exc:
        summary["learning_analysis_error"] = str(exc)[:80]

    apply_backtest_results(summary)
    print(json.dumps({k: summary[k] for k in summary if k != "per_symbol"}, indent=2))


if __name__ == "__main__":
    main()
