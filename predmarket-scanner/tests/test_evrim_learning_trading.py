"""Evrim — learning ≠ trading off (7 integration tests)."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from elite_trader.order_gate import ORDER_ROUTE_LIVE, build_order_intent, route_order
from elite_trader.evrim_risk_governor import EXTREME_STOP_REASONS, assess_evrim_risk, is_extreme_stop


def _profile() -> dict:
    return {
        "evrim_v2_min_final_score": 55,
        "evrim_v2_max_daily_drawdown_pct": 12,
        "evrim_v2_half_risk_drawdown_pct": 8,
        "evrim_v2_fee_gross_caution": 0.45,
        "evrim_v2_fee_gross_recovery": 0.75,
        "evrim_v2_config_auto_apply": False,
        "tp_stake_pct": 0.0042,
    }


class TestEvrimLearningTrading(unittest.TestCase):
    def test_01_learning_active_never_blocks_trading_flag(self):
        from elite_trader.evrim_learning_runtime import (
            begin_learning_task,
            finish_learning_task,
            learning_blocks_trading,
            learning_snapshot,
        )

        begin_learning_task("maybe_tune")
        snap = learning_snapshot()
        self.assertTrue(snap.get("learning_active"))
        self.assertFalse(snap.get("learning_blocks_trading"))
        self.assertFalse(learning_blocks_trading())
        finish_learning_task({"ok": True})

    def test_02_candidate_does_not_change_active_version(self):
        from elite_trader.evrim_config_version import (
            bootstrap_active_from_profile,
            config_version_snapshot,
            set_candidate,
        )

        bootstrap_active_from_profile()
        before = config_version_snapshot().get("active_config_version")
        set_candidate({"max_open": 99}, source="unittest", task_type="test")
        after = config_version_snapshot()
        self.assertEqual(after.get("active_config_version"), before)
        self.assertIsNotNone(after.get("candidate_config_version"))

    def test_03_pending_approval_trading_uses_active_config(self):
        from elite_trader.evrim_config_version import (
            bootstrap_active_from_profile,
            get_active_config,
            get_trading_profile,
            set_candidate,
        )

        bootstrap_active_from_profile()
        active = get_active_config()
        active_max = active.get("max_open")
        set_candidate({"max_open": 99, "evrim_v2_min_final_score": 99}, source="test")
        trading = get_trading_profile({"max_open": 77, "evrim_v2_min_final_score": 40})
        self.assertEqual(trading.get("max_open"), active_max)
        self.assertEqual(trading.get("evrim_v2_min_final_score"), active.get("evrim_v2_min_final_score"))

    def test_04_backtest_task_does_not_block_order_route(self):
        from elite_trader.evrim_learning_runtime import begin_learning_task

        begin_learning_task("backtest")
        g = route_order(
            "evrim",
            build_order_intent("evrim", symbol="BTCUSDT", side="LONG"),
            active_futures_mode="evrim",
            api_healthy=True,
            live_orders_enabled=True,
        )
        self.assertEqual(g.order_route, ORDER_ROUTE_LIVE)
        self.assertTrue(g.send_live)

    def test_05_paper_forward_learning_no_global_halt(self):
        from elite_trader.evrim_learning_runtime import begin_learning_task, learning_snapshot

        begin_learning_task("paper_forward")
        snap = learning_snapshot()
        self.assertFalse(snap.get("learning_blocks_trading"))
        self.assertTrue(snap.get("trading_continues_during_learning"))

    def test_06_stop_new_entries_only_extreme(self):
        cautious = assess_evrim_risk(
            {"symbol": "BTCUSDT", "evrim_hybrid": {"expected_net_pnl_usd": 1.0}},
            {"fee_gross_ratio": 0.50, "daily_drawdown_pct": 9},
            _profile(),
            {"final_score": 80, "sentinel_risk_off": True, "sentinel_recommended_risk_mode": "reduce_size"},
            execution_path="live",
        )
        self.assertFalse(cautious.get("risk_veto"))
        self.assertIn(cautious.get("risk_level"), ("cautious", "reduce_size", "recovery", "normal"))

        extreme = assess_evrim_risk(
            {"symbol": "BTCUSDT"},
            {"api_latency_ms": 3000},
            _profile(),
            {"final_score": 80},
            execution_path="live",
        )
        self.assertTrue(extreme.get("risk_veto"))
        self.assertIn(extreme.get("risk_veto_reason"), EXTREME_STOP_REASONS)
        self.assertTrue(is_extreme_stop(extreme))

    def test_07_validated_patch_without_approval_unchanged_profile(self):
        from elite_trader.evrim_param_validator import apply_validated_patch
        from elite_trader.mode_profiles import get_profile

        before = dict(get_profile("evrim") or {})
        old_max = before.get("max_open")
        report = {
            "accepted": True,
            "patch": {"max_open": 77},
            "backup_path": None,
            "comparison": {},
        }
        result = apply_validated_patch(report)
        after = dict(get_profile("evrim") or {})
        self.assertTrue(result.get("candidate_only") or result.get("proposed"))
        self.assertEqual(after.get("max_open"), old_max)


if __name__ == "__main__":
    unittest.main()
