"""
Evrim — parametre değişiminde otomatik test, karşılaştırma, kabul/rollback.

Akış: backup → simülasyon BT (journal proxy + kline) → 30dk forward → metrik karşılaştır → kabul/rollback.
Canlı profile yalnızca test geçerse güncellenir.
"""
from __future__ import annotations

import json
import os
import sys
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from elite_trader.evrim_opportunity import MODE_ID
from elite_trader.evrim_trade_learning import (
    backup_evrim_profile,
    clamp_parameter_patch,
    load_recent_trades,
)
from elite_trader.mode_profiles import get_profile, save_profile

_ROOT = Path(__file__).resolve().parent.parent

JOURNAL_BT_LIMIT = 500
FORWARD_MINUTES = 30
MIN_PROFIT_FACTOR = 1.15
MAX_FEE_RATIO_PCT = 72.0
DD_TOLERANCE = 1.08

FORWARD_SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def compute_performance_metrics(records: list[dict[str, Any]]) -> dict[str, Any]:
    """10 metrik — trade journal veya sim kayıtlarından."""
    if not records:
        return {"trade_count": 0, "net_pnl": 0.0}

    nets: list[float] = []
    fees = 0.0
    gross_profit = 0.0
    gross_loss = 0.0
    wins: list[float] = []
    losses: list[float] = []
    slip_sum = 0.0
    hold_sum = 0.0
    max_consec_loss = 0
    cur_consec = 0
    peak = 0.0
    equity = 0.0
    max_dd = 0.0
    stake_sum = 0.0

    for r in records:
        net = float(r.get("net_pnl") or 0)
        nets.append(net)
        equity += net
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
        fee = float(r.get("fee") or 0)
        fees += fee
        hold_sum += float(r.get("hold_time_sec") or 300)
        slip_sum += float(r.get("slippage_bps") or 0)
        stake_sum += float(r.get("stake_usd") or 140)
        if net > 0:
            gross_profit += net
            wins.append(net)
            cur_consec = 0
        else:
            gross_loss += abs(net)
            losses.append(net)
            cur_consec += 1
            max_consec_loss = max(max_consec_loss, cur_consec)

    n = len(records)
    net_pnl = sum(nets)
    pf = gross_profit / gross_loss if gross_loss > 1e-9 else (99.0 if gross_profit > 0 else 0.0)
    fee_ratio_pct = fees / gross_profit * 100 if gross_profit > 1e-9 else (100.0 if fees else 0.0)
    hold_hours = max(hold_sum / 3600.0, 0.01)
    avg_stake = stake_sum / n if n else 140.0
    liq_risk = (max_consec_loss * (sum(losses) / len(losses) if losses else 0)) / max(avg_stake, 1.0)
    slip_cost_est = avg_stake * (slip_sum / n / 10000.0) * 2 if n else 0
    slip_eff = net_pnl / max(slip_cost_est, 0.01) if n else 0.0

    return {
        "trade_count": n,
        "net_pnl": round(net_pnl, 4),
        "max_drawdown": round(max_dd, 4),
        "fee_ratio_pct": round(fee_ratio_pct, 2),
        "profit_factor": round(pf, 3),
        "avg_win": round(sum(wins) / len(wins), 4) if wins else 0.0,
        "avg_loss": round(sum(losses) / len(losses), 4) if losses else 0.0,
        "pnl_velocity": round(net_pnl / hold_hours, 4),
        "consecutive_loss_max": max_consec_loss,
        "liquidation_risk": round(liq_risk, 3),
        "slippage_efficiency": round(slip_eff, 3),
        "avg_slippage_bps": round(slip_sum / n, 2) if n else 0.0,
        "win_rate_pct": round(len(wins) / n * 100, 1) if n else 0.0,
    }


def compare_metrics(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
) -> dict[str, Any]:
    """Eski vs yeni — kabul kuralları."""
    checks: list[dict[str, Any]] = []
    passed = True

    def _chk(name: str, ok: bool, detail: str) -> None:
        nonlocal passed
        checks.append({"name": name, "ok": ok, "detail": detail})
        if not ok:
            passed = False

    b_net = float(baseline.get("net_pnl") or 0)
    c_net = float(candidate.get("net_pnl") or 0)
    _chk("net_pnl_better", c_net > b_net, f"candidate ${c_net:.2f} vs baseline ${b_net:.2f}")

    b_dd = float(baseline.get("max_drawdown") or 0)
    c_dd = float(candidate.get("max_drawdown") or 0)
    dd_ok = c_dd <= b_dd * DD_TOLERANCE + 0.01 if b_dd > 0 else c_dd <= b_dd + 5
    _chk("drawdown_not_worse", dd_ok, f"candidate DD ${c_dd:.2f} vs baseline ${b_dd:.2f}")

    c_fee = float(candidate.get("fee_ratio_pct") or 0)
    b_fee = float(baseline.get("fee_ratio_pct") or 0)
    fee_ok = c_fee <= MAX_FEE_RATIO_PCT and (
        c_fee <= b_fee * 1.15 if b_fee > 0 else c_fee <= MAX_FEE_RATIO_PCT
    )
    _chk("fee_ratio_ok", fee_ok, f"candidate fee/gross {c_fee:.1f}% (max {MAX_FEE_RATIO_PCT}%)")

    c_pf = float(candidate.get("profit_factor") or 0)
    _chk("profit_factor_min", c_pf >= MIN_PROFIT_FACTOR, f"PF={c_pf:.2f} need >={MIN_PROFIT_FACTOR}")

    c_slip = float(candidate.get("slippage_efficiency") or 0)
    b_slip = float(baseline.get("slippage_efficiency") or 0)
    slip_ok = c_slip >= b_slip * 0.8 if b_slip > 0 else c_slip >= -2
    _chk("slippage_controlled", slip_ok, f"slip_eff {c_slip:.2f} vs {b_slip:.2f}")

    return {
        "passed": passed,
        "checks": checks,
        "baseline": baseline,
        "candidate": candidate,
        "delta": {
            k: round(float(candidate.get(k) or 0) - float(baseline.get(k) or 0), 4)
            for k in (
                "net_pnl",
                "max_drawdown",
                "fee_ratio_pct",
                "profit_factor",
                "trade_count",
                "pnl_velocity",
            )
        },
    }


def run_journal_baseline_metrics(limit: int = JOURNAL_BT_LIMIT) -> dict[str, Any]:
    """Son N gerçek/sim journal işlemi — mevcut ayar performansı."""
    return compute_performance_metrics(load_recent_trades(limit))


def run_profile_backtest(
    profile: dict[str, Any],
    *,
    days: int = 2,
    max_symbols: int = 3,
) -> dict[str, Any]:
    """Kline hybrid backtest — aday profil (canlıya yazılmaz)."""
    sys.path.insert(0, str(_ROOT))
    from scripts.evrim_mtf_backtest import SYMBOLS, backtest_symbol

    sim_records: list[dict[str, Any]] = []
    per_sym: list[dict[str, Any]] = []
    try:
        from binance_futures_trader.client import BinanceFuturesClient

        client = BinanceFuturesClient()
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:80], "metrics": {}}

    prof = dict(profile)
    prof["evrim_expectancy_min_net_usd"] = 0.0
    prof["evrim_expectancy_bt_simulation"] = True

    for sym in SYMBOLS[:max_symbols]:
        coin = sym.replace("USDT", "")
        try:
            candles = client.klines_history(coin, "5m", days=days) or []
        except Exception as exc:
            per_sym.append({"symbol": sym, "error": str(exc)[:60]})
            continue
        r = backtest_symbol(candles, prof, sym)
        per_sym.append(r)
        wins = int(r.get("wins") or 0)
        losses = int(r.get("trades", 0) or 0) - wins
        stake = float(prof.get("min_stake_usd") or 140)
        tp = float(prof.get("tp_stake_pct") or 0.006)
        sl = float(prof.get("sl_stake_pct") or 0.0025)
        for _ in range(wins):
            sim_records.append(
                {
                    "net_pnl": stake * tp * 0.98 - stake * 0.005,
                    "fee": stake * 0.005,
                    "hold_time_sec": 400,
                    "slippage_bps": 8,
                    "stake_usd": stake,
                }
            )
        for _ in range(max(0, losses)):
            sim_records.append(
                {
                    "net_pnl": -stake * sl - stake * 0.005,
                    "fee": stake * 0.005,
                    "hold_time_sec": 350,
                    "slippage_bps": 10,
                    "stake_usd": stake,
                }
            )

    metrics = compute_performance_metrics(sim_records)
    total_trades = sum(r.get("trades", 0) for r in per_sym)
    total_wins = sum(r.get("wins", 0) for r in per_sym)
    wr = round(total_wins / total_trades * 100, 1) if total_trades else 0
    return {
        "ok": True,
        "mode": "kline_backtest",
        "days": days,
        "symbols_n": len(per_sym),
        "win_rate_pct": wr,
        "total_trades": total_trades,
        "metrics": metrics,
        "per_symbol": per_sym,
    }


def run_forward_test(
    profile: dict[str, Any],
    *,
    minutes: int = FORWARD_MINUTES,
    max_symbols: int = 5,
) -> dict[str, Any]:
    """Son N dakika kline — simülasyon giriş/çıkış."""
    sys.path.insert(0, str(_ROOT))
    from scripts.evrim_mtf_backtest import (
        LOOKBACK,
        MOM_THRESH,
        _build_bt_ctx,
        _strength,
    )
    from elite_trader.evrim_hybrid_scorer import evaluate
    from elite_trader.evrim_dynamic_exit import compute_dynamic_exit, simulate_bt_exit

    try:
        from binance_futures_trader.client import BinanceFuturesClient

        client = BinanceFuturesClient()
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:80], "metrics": {}}

    prof = dict(profile)
    prof["evrim_expectancy_min_net_usd"] = 0.0
    prof["evrim_expectancy_bt_simulation"] = True

    cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    sim_records: list[dict[str, Any]] = []
    signals = 0

    for sym in FORWARD_SYMBOLS[:max_symbols]:
        coin = sym.replace("USDT", "")
        try:
            candles = client.klines_history(coin, "5m", days=1) or []
        except Exception:
            continue
        if len(candles) < LOOKBACK + 12:
            continue
        for i in range(LOOKBACK, len(candles) - 4):
            ts = candles[i].get("t") or candles[i].get("time")
            if ts:
                try:
                    if isinstance(ts, (int, float)):
                        dt = datetime.fromtimestamp(ts / 1000.0, tz=timezone.utc)
                    else:
                        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                    if dt < cutoff:
                        continue
                except Exception:
                    pass
            window = candles[i - LOOKBACK : i]
            price = float(candles[i]["c"])
            old = float(window[0]["c"])
            change = ((price - old) / old) * 100 if old else 0.0
            if abs(change) <= MOM_THRESH:
                continue
            side = "LONG" if change > 0 else "SHORT"
            sig = {"symbol": sym, "type": side, "change": change, "strength": _strength(change)}
            bt_ctx = _build_bt_ctx(candles, i, sym)
            dec = evaluate(sig, prof, log_decision=False, ctx_override=bt_ctx)
            signals += 1
            if not dec.ok:
                continue
            entry = float(candles[i + 1]["o"])
            if entry <= 0:
                continue
            plan = compute_dynamic_exit(
                total_score=float(dec.total_score or 70),
                side=side,
                signal=sig,
                ctx=dec.context or bt_ctx,
                profile=prof,
            )
            win, _, tag = simulate_bt_exit(
                side=side, entry=entry, candles=candles, start_idx=i + 2, plan=plan
            )
            stake = float(prof.get("min_stake_usd") or 140)
            net = (
                stake * plan.tp_stake_pct * plan.tp_trigger_frac - stake * 0.005
                if win
                else -stake * plan.sl_stake_pct - stake * 0.005
            )
            sim_records.append(
                {
                    "net_pnl": net,
                    "fee": stake * 0.005,
                    "hold_time_sec": minutes * 60 / 2,
                    "slippage_bps": float(bt_ctx.get("spread_pct") or 0) * 10,
                    "stake_usd": stake,
                    "exit_reason": tag,
                }
            )

    return {
        "ok": True,
        "mode": "forward",
        "minutes": minutes,
        "signals": signals,
        "trades": len(sim_records),
        "metrics": compute_performance_metrics(sim_records),
    }


def _merge_candidate_metrics(bt: dict[str, Any], fwd: dict[str, Any]) -> dict[str, Any]:
    """BT + forward birleşik aday metrik."""
    bm = bt.get("metrics") or {}
    fm = fwd.get("metrics") or {}
    if not bm and not fm:
        return compute_performance_metrics([])
    n = int(bm.get("trade_count") or 0) + int(fm.get("trade_count") or 0)
    return {
        "trade_count": n,
        "net_pnl": round(float(bm.get("net_pnl") or 0) + float(fm.get("net_pnl") or 0), 4),
        "max_drawdown": round(
            max(float(bm.get("max_drawdown") or 0), float(fm.get("max_drawdown") or 0)), 4
        ),
        "fee_ratio_pct": round(
            (float(bm.get("fee_ratio_pct") or 0) + float(fm.get("fee_ratio_pct") or 0)) / 2,
            2,
        ),
        "profit_factor": round(
            (
                float(bm.get("profit_factor") or 0) * int(bm.get("trade_count") or 0)
                + float(fm.get("profit_factor") or 0) * int(fm.get("trade_count") or 0)
            )
            / max(1, n),
            3,
        ),
        "avg_win": round(
            (float(bm.get("avg_win") or 0) + float(fm.get("avg_win") or 0)) / 2, 4
        ),
        "avg_loss": round(
            (float(bm.get("avg_loss") or 0) + float(fm.get("avg_loss") or 0)) / 2, 4
        ),
        "pnl_velocity": round(
            float(bm.get("pnl_velocity") or 0) + float(fm.get("pnl_velocity") or 0), 4
        ),
        "consecutive_loss_max": max(
            int(bm.get("consecutive_loss_max") or 0),
            int(fm.get("consecutive_loss_max") or 0),
        ),
        "liquidation_risk": round(
            max(float(bm.get("liquidation_risk") or 0), float(fm.get("liquidation_risk") or 0)),
            3,
        ),
        "slippage_efficiency": round(
            (float(bm.get("slippage_efficiency") or 0) + float(fm.get("slippage_efficiency") or 0))
            / 2,
            3,
        ),
        "avg_slippage_bps": round(
            (float(bm.get("avg_slippage_bps") or 0) + float(fm.get("avg_slippage_bps") or 0)) / 2,
            2,
        ),
        "win_rate_pct": round(
            (
                float(bm.get("win_rate_pct") or 0) * int(bm.get("trade_count") or 0)
                + float(fm.get("win_rate_pct") or 0) * int(fm.get("trade_count") or 0)
            )
            / max(1, n),
            1,
        ),
    }


def rollback_evrim_profile(backup_path: str | None = None) -> dict[str, Any]:
    """Son backup'tan profile geri yükle."""
    path = backup_path
    if not path:
        try:
            from elite_trader.evrim_training import load_training_state

            paths = load_training_state().get("profile_backup_paths") or []
            path = str(_ROOT / paths[-1]) if paths else None
        except Exception:
            path = None
    if not path or not Path(path).is_file():
        return {"ok": False, "reason": "no_backup"}
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    modes = data.get("modes") or {}
    patch = modes.get(MODE_ID) or modes.get("evrim")
    if not patch:
        return {"ok": False, "reason": "no_evrim_in_backup"}
    save_profile(MODE_ID, patch)
    return {"ok": True, "restored_from": path}


def validate_parameter_change(
    patch: dict[str, Any],
    *,
    bt_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Tam otomatik test pipeline. Canlı profile yazmaz.
    """
    patch = clamp_parameter_patch(patch)
    backup_path = backup_evrim_profile()
    old_profile = get_profile(MODE_ID) or {}
    candidate_profile = deepcopy(old_profile)
    candidate_profile.update(patch)

    baseline = run_journal_baseline_metrics(JOURNAL_BT_LIMIT)
    bt = run_profile_backtest(candidate_profile, days=2, max_symbols=3)
    fwd = run_forward_test(candidate_profile, minutes=FORWARD_MINUTES)
    candidate_metrics = _merge_candidate_metrics(bt, fwd)

    comparison = compare_metrics(baseline, candidate_metrics)
    report = {
        "at": _now_iso(),
        "backup_path": backup_path,
        "patch": patch,
        "baseline_journal_n": baseline.get("trade_count"),
        "baseline": baseline,
        "candidate": candidate_metrics,
        "comparison": comparison,
        "backtest_block": {"ok": bt.get("ok"), "wr": bt.get("win_rate_pct"), "trades": bt.get("total_trades")},
        "forward_block": {
            "ok": fwd.get("ok"),
            "minutes": fwd.get("minutes"),
            "trades": fwd.get("trades"),
        },
        "accepted": comparison.get("passed"),
    }

    try:
        from elite_trader.evrim_training import load_training_state, _save_training_state

        st = load_training_state()
        hist = st.setdefault("param_validation_history", [])
        hist.append(report)
        st["param_validation_history"] = hist[-30:]
        st["last_param_validation"] = report
        _save_training_state(st)
    except Exception:
        pass

    return report


def apply_validated_patch(report: dict[str, Any]) -> dict[str, Any]:
    """Test geçtiyse candidate öner; auto_apply açıksa profile yaz."""
    if not report.get("accepted"):
        rb = rollback_evrim_profile(report.get("backup_path"))
        return {
            "ok": False,
            "rolled_back": rb.get("ok"),
            "reason": "validation_failed",
            "checks": (report.get("comparison") or {}).get("checks"),
        }
    patch = report.get("patch") or {}
    patch = clamp_parameter_patch(patch)

    from elite_trader.mode_profiles import get_profile

    prof = get_profile(MODE_ID) or {}
    auto = bool(prof.get("evrim_v2_config_auto_apply", False))

    if not auto:
        from elite_trader.evrim_config_pipeline import propose_config_change

        proposed = propose_config_change(
            patch,
            reason="param_validator",
            source="param_validator",
            backtest_passed=True,
            task_type="backtest",
            risk_change=str((report.get("comparison") or {}).get("risk_change") or ""),
            expected_improvement=(report.get("comparison") or {}).get("expected_improvement") or "",
        )
        try:
            from elite_trader.evrim_training import load_training_state, _save_training_state

            st = load_training_state()
            st["pending_parameter_patch"] = {}
            st["pending_patch_requires_backtest"] = False
            st["last_candidate_patch"] = patch
            st["last_candidate_patch_at"] = _now_iso()
            _save_training_state(st)
        except Exception:
            pass
        return {
            "ok": True,
            "proposed": proposed,
            "applied": {},
            "backup": report.get("backup_path"),
            "candidate_only": True,
        }

    save_profile(MODE_ID, patch)
    try:
        from elite_trader.evrim_config_version import promote_candidate_on_approval

        promote_candidate_on_approval(patch)
    except Exception:
        pass
    try:
        from elite_trader.evrim_training import load_training_state, _save_training_state

        st = load_training_state()
        st["pending_parameter_patch"] = {}
        st["pending_patch_requires_backtest"] = False
        st["last_applied_patch"] = patch
        st["last_applied_patch_at"] = _now_iso()
        st["last_applied_patch_backup"] = report.get("backup_path")
        _save_training_state(st)
    except Exception:
        pass
    return {"ok": True, "applied": patch, "backup": report.get("backup_path")}


def validate_and_apply_pending_patch(
    bt_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Pending patch varsa tam test + kabul/rollback."""
    try:
        from elite_trader.evrim_training import load_training_state
    except Exception:
        return {"ok": False, "reason": "training_unavailable"}

    st = load_training_state()
    pending = st.get("pending_parameter_patch") or {}
    if not pending or not st.get("pending_patch_requires_backtest"):
        return {"ok": True, "skipped": "no_pending_patch"}

    report = validate_parameter_change(pending, bt_summary=bt_summary)
    result = apply_validated_patch(report)
    result["validation_report"] = report
    return result
