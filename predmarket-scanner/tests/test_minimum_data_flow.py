"""V2 minimum data flow + zero-data guard tests."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch


class TestMinimumDataFlow(unittest.TestCase):
    def test_hunter_zero_trade_observation(self):
        from elite_trader.hunter_paper_exploration import try_hunter_exploration

        signal = {
            "symbol": "BTCUSDT",
            "type": "LONG",
            "strength": "Weak",
            "change": 0.3,
            "hunter_meta": {"breakout_score": 50, "fake_breakout_risk": 80},
        }
        action, reason, _ = try_hunter_exploration(signal, {}, {}, "no_breakout")
        self.assertEqual(action, "observation")

    def test_chop_trend_guard_observation_only(self):
        from elite_trader.chop_paper_exploration import try_chop_exploration

        signal = {
            "symbol": "ETHUSDT",
            "type": "LONG",
            "chop_meta": {"chop_score": 70, "trend_guard_active": True},
        }
        action, reason, _ = try_chop_exploration(signal, {}, {"chop_hunter_breakout_veto": 70}, "trend")
        self.assertEqual(action, "observation")
        self.assertIn("trend_guard", reason)

    def test_sentinel_benchmark_force(self):
        from elite_trader.sentinel_benchmark import force_benchmark, get_dashboard

        force_benchmark({"symbol": "BTCUSDT", "type": "LONG"}, {"sentinel_quality_score": 72})
        dash = get_dashboard()
        self.assertIsNotNone(dash.get("sentinel_benchmark"))

    def test_evrim_zero_data_guard_no_bad_strategy(self):
        from elite_trader.evrim_zero_data_guard import classify_mode_data_status

        cls = classify_mode_data_status(
            "hunter",
            paper_trade_count=0,
            decision_count=120,
            reject_count=120,
        )
        self.assertEqual(cls["mode_data_status"], "no_trade_due_to_filters")
        self.assertFalse(cls.get("strategy_bad"))

    def test_paper_exploration_never_live_send(self):
        from elite_trader.mode_minimum_data import assess_minimum_data

        md = assess_minimum_data("hunter", {"open": [], "closed": []})
        self.assertTrue(md.get("minimum_data_never_live"))

    def test_minimum_data_only_paper_modes(self):
        from elite_trader.mode_minimum_data import assess_minimum_data

        self.assertFalse(assess_minimum_data("berserk", {"open": [], "closed": []}).get("active") is None)
        md = assess_minimum_data("hunter", {"open": [], "closed": []})
        self.assertTrue(md.get("minimum_data_only_paper"))

    def test_active_futures_evrim_paper_shadow(self):
        from elite_trader.order_gate import route_order
        from elite_trader.panel_strategy import is_live_binance_motor

        with patch("elite_trader.panel_strategy.active_futures_mode", return_value="evrim"):
            self.assertFalse(is_live_binance_motor("hunter"))
            r = route_order(
                "hunter",
                {"symbol": "BTCUSDT", "side": "BUY"},
                active_futures_mode="evrim",
                live_orders_enabled=True,
            )
            self.assertTrue(r.is_paper)

    def test_evrim_live_decisions_buffer(self):
        from elite_trader.evrim_live_decisions import get_panel, record_decision

        record_decision(symbol="BTCUSDT", side="LONG", allowed=False, reason="test_reject")
        panel = get_panel()
        self.assertGreaterEqual(panel.get("evrim_live_decision_count", 0), 1)
        self.assertIn("parallel paper", panel.get("note", ""))

    def test_reject_ring_buffer(self):
        from elite_trader.mode_reject_buffer import append_reject, get_rejects, summary

        append_reject("hunter", {"symbol": "X", "reason": "test_buf", "strength": "Medium"})
        self.assertGreaterEqual(summary("hunter").get("reject_count", 0), 1)
        self.assertTrue(any(r.get("reason") == "test_buf" for r in get_rejects("hunter", limit=5)))


if __name__ == "__main__":
    unittest.main()
