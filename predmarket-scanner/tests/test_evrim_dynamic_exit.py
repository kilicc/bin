"""Smoke tests — dinamik TP/SL bantları."""
from __future__ import annotations

from elite_trader.evrim_dynamic_exit import compute_dynamic_exit, simulate_bt_exit


def test_score_band_70():
    plan = compute_dynamic_exit(
        total_score=70,
        side="LONG",
        signal={"change": 0.5, "strength": "Medium"},
        ctx={"atr_pct": 0.08, "vol_ratio": 1.2, "spread_pct": 0.05},
        profile={"evrim_dynamic_exit_enabled": True},
    )
    assert 0.002 <= plan.tp_stake_pct <= 0.012
    assert 0.001 <= plan.sl_stake_pct <= 0.008
    assert plan.partial_tp_frac == 0.5


def test_score_band_90():
    plan = compute_dynamic_exit(
        total_score=92,
        side="LONG",
        signal={"change": 1.1, "strength": "Strong"},
        ctx={
            "atr_pct": 0.1,
            "vol_ratio": 2.0,
            "spread_pct": 0.04,
            "market_regime": "trending",
        },
        profile={"evrim_dynamic_exit_enabled": True},
    )
    assert plan.tp_stake_pct >= plan.sl_stake_pct
    assert plan.tp_stake_pct_display >= 0.75


def test_bt_sim_win():
    from elite_trader.evrim_dynamic_exit import DynamicExitPlan

    plan = DynamicExitPlan(tp_stake_pct=0.005, sl_stake_pct=0.002, partial_tp_frac=0.5)
    candles = [
        {"h": 100, "l": 100, "c": 100},
        {"h": 101.2, "l": 99.8, "c": 101},
        {"h": 102, "l": 100, "c": 101.5},
    ]
    win, partial, tag = simulate_bt_exit(
        side="LONG", entry=100.0, candles=candles, start_idx=1, plan=plan
    )
    assert win or partial
    assert tag in ("TP", "PARTIAL-TRAIL", "MOMENTUM-FADE", "TIMEOUT")
