"""
Evrim modu — günlük 2× hedef (~%4/saat ortalama PnL velocity), kârı koruyarak bileşik.

Yalnızca evrim profilini günceller; diğer modlara dokunmaz.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from elite_trader.mode_profiles import get_profile, save_profile
from elite_trader.parallel_universe_engine import get_books

MODE_ID = "evrim"
_ROOT = Path(__file__).resolve().parent.parent
_STATE_PATH = _ROOT / "data" / "evrim_adaptive_state.json"

_tune_lock = threading.Lock()
_last_tune_ts = 0.0
_MIN_TUNE_INTERVAL_SEC = 480.0  # 8 dk


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_state() -> dict[str, Any]:
    if not _STATE_PATH.is_file():
        return {"session_started_at": _now_iso(), "tune_history": [], "lessons": {}}
    try:
        return json.loads(_STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"session_started_at": _now_iso(), "tune_history": [], "lessons": {}}


def _save_state(st: dict[str, Any]) -> None:
    hist = st.get("tune_history") or []
    if len(hist) > 80:
        st["tune_history"] = hist[-80:]
    _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _STATE_PATH.write_text(
        json.dumps(st, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _pnl(row: dict[str, Any]) -> float:
    return float(row.get("final_pnl") or row.get("net_pnl") or 0)


def _parse_ts(row: dict[str, Any]) -> float | None:
    for key in ("exit_time", "closed_at", "entry_time", "opened_at_iso"):
        v = row.get(key)
        if not v:
            continue
        s = str(v).replace("Z", "+00:00")
        try:
            if "T" not in s and len(s) >= 19 and " " in s:
                s = s.replace(" ", "T", 1)
            return datetime.fromisoformat(s[:32]).timestamp()
        except Exception:
            continue
    return None


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def cross_mode_insights() -> dict[str, Any]:
    """Tüm mod kitaplarından öğren (Evrim hariç — patch için çapraz istatistik)."""
    books = get_books() or {}
    closed: list[dict[str, Any]] = []
    for mid, book in books.items():
        if mid == MODE_ID:
            continue
        closed.extend(book.get("closed") or [])
    if not closed:
        try:
            from elite_trader.evrim_cross_mode_learner import collect_all_closed_trades

            for row in collect_all_closed_trades():
                if str(row.get("panel_mode") or row.get("universe_id")) != MODE_ID:
                    closed.append(row)
        except Exception:
            pass
    if not closed:
        return {"n": 0}
    wins = [c for c in closed if _pnl(c) > 0]
    losses = [c for c in closed if _pnl(c) < 0]
    exits: dict[str, int] = {}
    for c in closed:
        r = str(c.get("exit_reason") or "?")[:20]
        exits[r] = exits.get(r, 0) + 1
    best_exit = max(exits, key=exits.get) if exits else "TP"
    return {
        "n": len(closed),
        "win_rate": len(wins) / len(closed) if closed else 0,
        "avg_win": sum(_pnl(c) for c in wins) / len(wins) if wins else 0,
        "avg_loss": sum(_pnl(c) for c in losses) / len(losses) if losses else 0,
        "best_exit": best_exit,
        "spike_share": sum(1 for c in closed if "SPIKE" in str(c.get("exit_reason") or ""))
        / len(closed),
    }


def _session_metrics(profile: dict[str, Any]) -> dict[str, Any]:
    """2× progress — tek kaynak: evrim_progress_engine.compute_progress."""
    from elite_trader.evrim_progress_engine import compute_progress

    book = (get_books() or {}).get(MODE_ID) or {}
    st = _load_state()
    prof = dict(profile)
    if st.get("session_started_at"):
        prof["_session_started_at"] = st["session_started_at"]

    prog = compute_progress(book, prof)
    closed = list(book.get("closed") or [])
    open_pos = list(book.get("open") or [])

    start = float(prog["daily_start_balance"])
    equity = float(prog["current_equity"])
    target = float(prog["target_equity"])

    hours = 1.0
    try:
        t0 = datetime.fromisoformat(
            str(st.get("session_started_at") or "").replace("Z", "+00:00")
        )
        hours = max(0.25, (datetime.now(timezone.utc) - t0).total_seconds() / 3600.0)
    except Exception:
        pass

    progress_24h = min(1.0, hours / 24.0)
    target_now = start + (target - start) * progress_24h
    pace_ratio = equity / target_now if target_now > 0 else 1.0

    now = time.time()
    recent = [c for c in closed if (_parse_ts(c) or 0) >= now - 3600]
    pnl_1h = sum(_pnl(c) for c in recent)
    pnl_per_min = pnl_1h / 60.0 if recent else 0.0
    needed_per_hour_usd = max(0.0, (target_now - equity) / max(0.25, 24.0 - hours))

    last10 = closed[-10:]
    recent_wr = (
        sum(1 for c in last10 if _pnl(c) > 0) / len(last10) if last10 else None
    )

    realized = float(prog.get("realized_pnl") or 0)
    return {
        **prog,
        "starting_balance": start,
        "equity": round(equity, 2),
        "realized": round(realized, 2),
        "unrealized": round(equity - start - realized, 2),
        "hours_elapsed": round(hours, 2),
        "target_now_usd": round(target_now, 2),
        "pace_ratio": round(pace_ratio, 4),
        "pnl_per_min": round(pnl_per_min, 4),
        "pnl_1h_usd": round(pnl_1h, 2),
        "needed_per_hour_usd": round(needed_per_hour_usd, 2),
        "recent_wr": recent_wr,
        "open_n": len(open_pos),
        "closed_n": len(closed),
    }


def _build_patch(
    profile: dict[str, Any],
    metrics: dict[str, Any],
    lessons: dict[str, Any],
) -> dict[str, Any]:
    """Anlık pace + PnL/min + kardeş modlardan çıkarılan dersler."""
    pace = float(metrics.get("pace_ratio") or 1.0)
    pnl_min = float(metrics.get("pnl_per_min") or 0.0)
    wr = metrics.get("recent_wr")

    edge = float(profile.get("min_edge") or 0.10)
    formula = float(profile.get("min_formula_score") or 0.54)
    tp = float(profile.get("tp_stake_pct") or 0.006)
    sl = float(profile.get("sl_stake_pct") or 0.0025)
    trig = float(profile.get("tp_trigger_frac") or 0.98)
    active = float(profile.get("active_capital_pct") or 0.70)
    max_open = int(profile.get("max_open") or 11)
    stake_m = float(profile.get("entry_stake_mult") or 1.0)
    spike_on = bool(profile.get("spike_enabled", True))
    stale_min = float(profile.get("stale_min_age_min") or 0.5)
    spike_frac = float(profile.get("spike_max_tp_frac") or 0.82)

    patch: dict[str, Any] = {}

    min_score = float(profile.get("evrim_min_total_score") or 55)

    if pace < 0.94:
        patch["evrim_min_total_score"] = int(_clamp(min_score - 2, 50, 68))
        patch["min_formula_score"] = round(_clamp(formula - 0.02, 0.42, 0.75), 3)
        patch["active_capital_pct"] = round(_clamp(active + 0.04, 0.45, 0.92), 3)
        patch["entry_stake_mult"] = round(_clamp(stake_m + 0.04, 0.75, 1.25), 3)
        patch["max_open"] = int(_clamp(max_open + 1, 6, 18))
        patch["spike_enabled"] = True
        patch["tp_trigger_frac"] = round(_clamp(trig - 0.02, 0.88, 1.0), 3)
        patch["market_cooldown_min"] = max(0, int(profile.get("market_cooldown_min") or 2) - 1)
        patch["evrim_max_tier"] = "max_aggressive"
    elif pace > 1.06:
        patch["evrim_min_total_score"] = int(_clamp(min_score + 1, 52, 72))
        patch["active_capital_pct"] = round(_clamp(active - 0.03, 0.40, 0.88), 3)
        patch["tp_trigger_frac"] = round(_clamp(trig + 0.02, 0.90, 1.02), 3)
        patch["stale_min_age_min"] = round(_clamp(stale_min - 0.08, 0.08, 2.0), 2)
        patch["spike_max_tp_frac"] = round(_clamp(spike_frac - 0.04, 0.55, 0.95), 2)
        patch["max_open"] = int(_clamp(max_open - 1, 5, 16))

    if pnl_min > 0.15 and pace >= 1.0:
        patch["tp_stake_pct"] = round(_clamp(tp + 0.0003, 0.004, 0.012), 4)
        patch["stale_enabled"] = True
    elif pnl_min < -0.08:
        patch["sl_stake_pct"] = round(_clamp(sl - 0.0002, 0.001, 0.006), 4)
        patch["min_hold_before_sl_sec"] = int(
            _clamp(float(profile.get("min_hold_before_sl_sec") or 20) + 5, 8, 90)
        )
        patch["entry_skip_cautious"] = True

    if wr is not None and wr < 0.4 and (metrics.get("closed_n") or 0) >= 8:
        patch["evrim_min_total_score"] = int(
            _clamp(min_score + 2, 55, 70)
        )
        patch["evrim_max_tier"] = "aggressive"
        patch["entry_block_weak"] = True
    elif pace < 1.0 and (metrics.get("closed_n") or 0) >= 4:
        patch.setdefault(
            "evrim_min_total_score",
            int(_clamp(min_score, 52, 65)),
        )

    if lessons.get("n", 0) >= 20:
        if lessons.get("spike_share", 0) > 0.35:
            patch["spike_enabled"] = True
            patch["spike_min_age_sec"] = round(
                _clamp(float(profile.get("spike_min_age_sec") or 18) - 2, 4, 60), 1
            )
        if lessons.get("win_rate", 0) > 0.55 and lessons.get("avg_win", 0) > abs(
            lessons.get("avg_loss", 0) or 1
        ):
            patch["tp_trigger_frac"] = round(
                _clamp(trig - 0.01, 0.90, 1.0), 3
            )

    try:
        from elite_trader.evrim_opportunity import _load_state

        ev = (_load_state().get("evolution") or {})
        lc = int(ev.get("losses_chop") or 0)
        wt = int(ev.get("wins_trend") or 0)
        if lc > wt + 2:
            patch["evrim_vol_mult"] = round(
                _clamp(float(profile.get("evrim_vol_mult") or 1.8) + 0.1, 1.5, 2.5),
                2,
            )
            patch["evrim_atr_min_pct"] = round(
                _clamp(float(profile.get("evrim_atr_min_pct") or 0.055) + 0.01, 0.04, 0.15),
                3,
            )
        elif wt > lc + 3:
            patch["evrim_vol_mult"] = round(
                _clamp(float(profile.get("evrim_vol_mult") or 1.8) - 0.05, 1.4, 2.2),
                2,
            )
    except Exception:
        pass

    try:
        from elite_trader.evrim_training import load_last_backtest

        bt = load_last_backtest() or {}
        bt_wr = bt.get("win_rate_pct")
        if bt_wr is not None and int(bt.get("total_trades") or 0) >= 15:
            if float(bt_wr) < 48:
                patch.setdefault(
                    "evrim_min_total_score",
                    int(_clamp(min_score + 1, 52, 72)),
                )
            elif float(bt_wr) > 58:
                patch.setdefault(
                    "evrim_min_total_score",
                    int(_clamp(min_score - 1, 50, 68)),
                )
            if bt.get("evrim_max_tier"):
                patch.setdefault("evrim_max_tier", bt["evrim_max_tier"])
            fake_rate = bt.get("fake_breakout_rate_pct")
            if fake_rate is not None and float(fake_rate) > 28:
                cur_veto = float(
                    profile.get("evrim_pa_fake_veto_threshold") or 0.72
                )
                patch.setdefault(
                    "evrim_pa_fake_veto_threshold",
                    round(_clamp(cur_veto - 0.03, 0.60, 0.80), 2),
                )
            if bt.get("evrim_pa_fake_veto_threshold") is not None:
                patch.setdefault(
                    "evrim_pa_fake_veto_threshold",
                    float(bt["evrim_pa_fake_veto_threshold"]),
                )
            spread_veto_rate = bt.get("spread_veto_rate_pct")
            if spread_veto_rate is not None and float(spread_veto_rate) > 5:
                cur_sp = float(profile.get("evrim_vo_spread_veto_pct") or 0.12)
                patch.setdefault(
                    "evrim_vo_spread_veto_pct",
                    round(_clamp(cur_sp - 0.01, 0.08, 0.20), 3),
                )
            if bt.get("evrim_vo_spread_veto_pct") is not None:
                patch.setdefault(
                    "evrim_vo_spread_veto_pct",
                    float(bt["evrim_vo_spread_veto_pct"]),
                )
            regime_wr = bt.get("regime_wr") or {}
            chop_wr = regime_wr.get("chop")
            trend_wr = regime_wr.get("trending")
            enter_rate = bt.get("enter_rate_pct")
            if enter_rate is not None and float(enter_rate) > 55 and chop_wr is not None and float(chop_wr) < 45:
                patch.setdefault(
                    "evrim_min_total_score",
                    int(_clamp(min_score + 1, 52, 72)),
                )
            if trend_wr is not None and float(trend_wr) > 52:
                patch.setdefault(
                    "tp_stake_pct",
                    round(_clamp(tp + 0.0002, 0.004, 0.012), 4),
                )
            if bt.get("regime_overrides"):
                patch.setdefault("regime_overrides", bt["regime_overrides"])
            dyn = bt.get("dynamic_exit_stats") or {}
            if dyn.get("avg_tp_pct_entered") and float(bt_wr or 0) > 54:
                patch.setdefault(
                    "tp_stake_pct",
                    round(_clamp(tp + 0.0002, 0.004, 0.012), 4),
                )
            if bt.get("dynamic_exit_overrides"):
                patch.setdefault("dynamic_exit_overrides", bt["dynamic_exit_overrides"])
            if bt.get("expectancy_overrides"):
                patch.setdefault("expectancy_overrides", bt["expectancy_overrides"])
            expm = bt.get("expectancy_metrics") or {}
            if float(expm.get("fee_to_gross_profit_pct") or 0) >= 45:
                patch.setdefault("evrim_max_tier", "aggressive")
            if expm.get("protection_mode") == "emergency":
                patch.setdefault("evrim_min_total_score", int(_clamp(min_score + 3, 58, 75)))
                patch["entry_stake_mult"] = round(_clamp(stake_m * 0.5, 0.5, 1.0), 3)
            avg_rv = bt.get("avg_rel_vol_entered")
            if (
                bt_wr is not None
                and float(bt_wr) < 48
                and avg_rv is not None
                and float(avg_rv) < 1.15
            ):
                patch.setdefault(
                    "evrim_min_total_score",
                    int(_clamp(min_score + 1, 52, 72)),
                )
    except Exception:
        pass

    return patch


def maybe_run_mtf_backtest(*, stale_hours: float = 6.0) -> dict[str, Any]:
    """Backtest bayat ise arka planda calistir (ayri proses, restart yok)."""
    import subprocess
    from datetime import datetime, timezone

    try:
        from elite_trader.mode_registry import enabled_mode_ids

        if "evrim" not in enabled_mode_ids():
            return {"ok": False, "skipped": "evrim disabled"}
        if os.getenv("ELITE_EVRIM_MTF_BACKTEST", "1").strip().lower() in (
            "0",
            "false",
            "no",
        ):
            return {"ok": False, "skipped": "backtest off"}
    except Exception:
        pass

    try:
        from elite_trader.evrim_training import load_training_state

        st = load_training_state()
        last = st.get("last_backtest_at")
        if last:
            try:
                t0 = datetime.fromisoformat(str(last).replace("Z", "+00:00")).timestamp()
                if time.time() - t0 < stale_hours * 3600:
                    return {"ok": False, "skipped": "fresh"}
            except Exception:
                pass
        script = _ROOT / "scripts" / "evrim_mtf_backtest.py"
        if not script.is_file():
            return {"ok": False, "error": "script missing"}
        subprocess.Popen(
            [sys.executable, str(script)],
            cwd=str(_ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        print("  🧬 Evrim MTF backtest arka planda baslatildi")
        try:
            from elite_trader.evrim_learning_runtime import begin_learning_task

            begin_learning_task("backtest")
        except Exception:
            pass
        return {"ok": True, "started": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def maybe_tune(*, force: bool = False) -> dict[str, Any]:
    global _last_tune_ts
    try:
        from elite_trader.mode_registry import enabled_mode_ids

        if "evrim" not in enabled_mode_ids():
            return {"ok": False, "skipped": "evrim disabled"}
    except Exception:
        pass
    profile = get_profile(MODE_ID)
    if not profile:
        return {"ok": False, "error": "profile missing"}
    if not profile.get("evrim_auto_tune", True) and not force:
        return {"ok": False, "skipped": "auto_tune off"}

    now = time.time()
    if not force and now - _last_tune_ts < _MIN_TUNE_INTERVAL_SEC:
        return {"ok": False, "skipped": "interval"}

    with _tune_lock:
        if not force and now - _last_tune_ts < _MIN_TUNE_INTERVAL_SEC:
            return {"ok": False, "skipped": "interval"}
        try:
            from elite_trader.evrim_learning_runtime import learning_task
        except Exception:
            learning_task = None  # type: ignore[assignment,misc]

        def _run_tune() -> dict[str, Any]:
            global _last_tune_ts
            metrics = _session_metrics(profile)
            lessons = cross_mode_insights()
            patch = _build_patch(profile, metrics, lessons)
            if not patch:
                _last_tune_ts = now
                maybe_run_mtf_backtest()
                return {"ok": True, "applied": {}, "metrics": metrics}

            from elite_trader.evrim_config_pipeline import propose_config_change

            result = propose_config_change(
                patch,
                reason="maybe_tune",
                source="maybe_tune",
                task_type="maybe_tune",
                source_modes=["berserk", "hunter", "chop_master", "sentinel"],
            )
            st = _load_state()
            st["lessons"] = lessons
            st["last_metrics"] = metrics
            st.setdefault("tune_history", []).append(
                {
                    "at": _now_iso(),
                    "pace_ratio": metrics.get("pace_ratio"),
                    "pnl_per_min": metrics.get("pnl_per_min"),
                    "patch": patch,
                    "config_pipeline": result,
                }
            )
            _save_state(st)
            _last_tune_ts = now
            if result.get("applied"):
                print(
                    f"  🧬 Evrim tune (auto) pace={metrics.get('pace_ratio')} "
                    f"PnL/min=${metrics.get('pnl_per_min')} → {list(patch.keys())}"
                )
            else:
                print(
                    f"  🧬 Evrim tune öneri (onay bekliyor) → {list(patch.keys())}"
                )
            maybe_run_mtf_backtest()
            return {
                "ok": True,
                "applied": patch if result.get("applied") else {},
                "proposed": result,
                "metrics": metrics,
                "learning_blocks_trading": False,
            }

        if learning_task:
            with learning_task("maybe_tune"):
                return _run_tune()
        return _run_tune()


def on_trade_closed(mode_id: str, closed: dict[str, Any]) -> None:
    if mode_id != MODE_ID:
        return
    try:
        from elite_trader.evrim_opportunity import on_trade_closed_evrim

        on_trade_closed_evrim(
            closed,
            {"regime": closed.get("market_regime")},
        )
    except Exception:
        pass
    pnl = _pnl(closed)
    try:
        from elite_trader.evrim_recovery import record_recovery_trade
        from elite_trader.evrim_risk_governor import record_sl, record_win

        if pnl <= 0 and "SL" in str(closed.get("exit_reason") or "").upper():
            profile = get_profile(MODE_ID) or {}
            record_sl(str(closed.get("symbol") or ""), profile)
        elif pnl > 0:
            record_win(str(closed.get("symbol") or ""))
        record_recovery_trade(pnl)
    except Exception:
        pass
    st = _load_state()
    st.setdefault("recent_closes", []).append(
        {"at": _now_iso(), "pnl": _pnl(closed), "reason": closed.get("exit_reason")}
    )
    if len(st["recent_closes"]) > 40:
        st["recent_closes"] = st["recent_closes"][-40:]
    _save_state(st)
    maybe_tune()


def reset_session() -> None:
    """Yalnızca oturum zaman damgası — evolution/tune_history silinmez."""
    global _last_tune_ts
    _last_tune_ts = 0.0
    st = _load_state()
    st["session_started_at"] = _now_iso()
    st.setdefault("tune_history", [])
    st.setdefault("lessons", {})
    _save_state(st)


def ensure_evrim_session() -> None:
    from elite_trader.evrim_cross_mode_learner import ensure_evrim_session as _ensure

    _ensure()
    try:
        from elite_trader.evrim_snapshot_loader import bootstrap_training_bias_on_session

        bootstrap_training_bias_on_session()
    except Exception:
        pass
    try:
        from elite_trader.evrim_cross_strategy_lab import ensure_persistent_learning

        ensure_persistent_learning()
    except Exception:
        pass
    try:
        from elite_trader.evrim_unified_engine import bootstrap_unified_engine

        bootstrap_unified_engine()
    except Exception:
        pass


def snapshot_for_ui() -> dict[str, Any]:
    profile = get_profile(MODE_ID) or {}
    metrics = _session_metrics(profile)
    st = _load_state()
    training_block: dict[str, Any] = {}
    try:
        from elite_trader.evrim_training import training_snapshot

        training_block = training_snapshot()
    except Exception:
        pass
    try:
        from elite_trader.evrim_opportunity import evolution_snapshot

        evolution = evolution_snapshot()
    except Exception:
        evolution = st.get("evolution") or {}
    try:
        from elite_trader.evrim_cross_strategy_lab import build_development_report

        cross_lab = build_development_report()
        if cross_lab.get("learning_level"):
            evolution = dict(evolution)
            evolution["level"] = max(
                int(evolution.get("level") or 1),
                int(cross_lab.get("learning_level") or 1),
            )
            evolution["title"] = cross_lab.get("level_title") or evolution.get("title")
            evolution["persistent_xp"] = cross_lab.get("total_xp")
            evolution["cross_strategy_lab"] = cross_lab
    except Exception:
        cross_lab = {}
    evrim_health: dict[str, Any] = {}
    try:
        from elite_trader.evrim_metrics import build_evrim_health
        from elite_trader.evrim_v2 import last_v2_meta, last_v2_risk
        from elite_trader.parallel_universe_engine import get_universe_book

        book = get_universe_book(MODE_ID) or {"open": [], "closed": []}
        evrim_health = build_evrim_health(
            book,
            profile,
            last_meta=last_v2_meta(),
            last_risk=last_v2_risk(),
        )
    except Exception:
        pass
    return {
        "mode_id": MODE_ID,
        "label": profile.get("label", "Evrim"),
        "auto_tune": profile.get("evrim_auto_tune", True),
        "daily_target_mult": profile.get("evrim_v2_daily_2x_mult", profile.get("evrim_daily_mult", 2.0)),
        "hourly_target_pct": profile.get("evrim_v2_hourly_target_pct", profile.get("evrim_hourly_target_pct", 4.0)),
        "evrim_min_total_score": profile.get("evrim_min_total_score", 55),
        "evrim_v2_min_final_score": profile.get("evrim_v2_min_final_score", 55),
        "metrics": metrics,
        "evolution": evolution,
        "evrim_health": evrim_health,
        "lessons": st.get("lessons") or cross_mode_insights(),
        "last_tune": (st.get("tune_history") or [])[-3:],
        "goal_note": "24s sonunda 2×; V2 meta-skor + risk governor + onaylı config",
        "live_training": training_block,
    }
