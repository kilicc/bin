"""Smoke tests — net expectancy."""
from __future__ import annotations

from elite_trader.evrim_expectancy import (
    apply_fee_protection_rules,
    compute_pre_trade_expectancy,
    gate_entry_from_expectancy,
    record_closed_trade,
    _recompute_derived,
)


def test_positive_expectancy():
    from elite_trader.evrim_expectancy import _default_metrics, save_expectancy_metrics

    save_expectancy_metrics(_default_metrics())
    bd = compute_pre_trade_expectancy(
        signal={"type": "LONG", "change": 0.8, "strength": "Strong"},
        ctx={"spread_pct": 0.04, "funding_abs": 0.0001, "atr_pct": 0.08, "vol_ratio": 1.3},
        profile={"evrim_dynamic_exit_enabled": True, "min_stake_usd": 140},
        total_score=82,
        dynamic_exit={"tp_stake_pct": 0.008, "tp_trigger_frac": 0.98},
        stake_usd=100,
        leverage=5,
    )
    ok, reason, _ = gate_entry_from_expectancy(
        bd, {"evrim_expectancy_min_net_usd": 0.01}
    )
    assert ok, reason
    assert bd.expected_net_pnl > 0


def test_negative_veto():
    bd = compute_pre_trade_expectancy(
        signal={"type": "LONG", "change": 0.1, "strength": "Weak"},
        ctx={"spread_pct": 0.25, "funding_abs": 0.002, "atr_pct": 0.02, "vol_ratio": 0.8},
        profile={"min_stake_usd": 140, "tp_stake_pct": 0.001, "sl_stake_pct": 0.002},
        total_score=66,
        dynamic_exit={"tp_stake_pct": 0.001, "tp_trigger_frac": 0.98},
    )
    ok, reason, _ = gate_entry_from_expectancy(bd, {"evrim_expectancy_min_net_usd": 0.5})
    assert not ok
    assert "expectancy" in reason.lower() or "negative" in reason.lower()


def test_fee_protection_emergency():
    m = _recompute_derived(
        {
            "trades_n": 20,
            "wins_n": 8,
            "losses_n": 12,
            "gross_profit_usd": 50,
            "gross_loss_usd": 40,
            "total_fees_usd": 55,
            "net_pnl_usd": -5,
        }
    )
    prot = apply_fee_protection_rules(m, {})
    assert prot["protection_mode"] == "emergency"
    assert prot["block_entries"]
