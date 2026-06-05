"""Evrim V2 — 12 integration test (yalnızca Evrim modu)."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from elite_trader.order_gate import ORDER_ROUTE_LIVE, ORDER_ROUTE_PAPER, build_order_intent, route_order, run_live_preflight_checks


def _profile_v2() -> dict:
    return {
        "role": "v2_live_meta_adaptive_brain",
        "evrim_v2_min_final_score": 55,
        "evrim_v2_aggressive_min": 78,
        "evrim_v2_high_conviction_min": 88,
        "evrim_v2_max_daily_drawdown_pct": 12,
        "evrim_v2_half_risk_drawdown_pct": 8,
        "evrim_v2_fee_gross_caution": 0.45,
        "evrim_v2_fee_gross_recovery": 0.75,
        "evrim_v2_spread_tp_veto_frac": 0.65,
        "evrim_v2_slippage_tp_veto_frac": 0.50,
        "evrim_v2_exploration_idle_min": 20,
        "evrim_v2_config_auto_apply": False,
        "tp_stake_pct": 0.0042,
        "sl_stake_pct": 0.0024,
        "starting_balance": 5000,
        "evrim_v2_daily_2x_mult": 2.0,
        "evrim_v2_hourly_target_pct": 4.0,
        "market_cooldown_min": 0.35,
    }


class TestEvrimV2Mode(unittest.TestCase):
    def test_01_non_evrim_active_is_paper(self):
        g = route_order(
            "berserk",
            build_order_intent("berserk", symbol="BTCUSDT", side="LONG"),
            active_futures_mode="evrim",
            api_healthy=True,
            live_orders_enabled=True,
        )
        self.assertEqual(g.order_route, ORDER_ROUTE_PAPER)
        self.assertFalse(g.send_live)

    def test_02_evrim_active_live_route_with_preflight(self):
        g = route_order(
            "evrim",
            build_order_intent("evrim", symbol="ETHUSDT", side="LONG"),
            active_futures_mode="evrim",
            api_healthy=True,
            live_orders_enabled=True,
        )
        self.assertEqual(g.order_route, ORDER_ROUTE_LIVE)
        self.assertTrue(g.send_live)
        self.assertFalse(g.allow_binance_send)
        g2 = run_live_preflight_checks(g, api_healthy=True)
        self.assertTrue(g2.allow_binance_send)

    def test_03_cross_mode_summaries_readable(self):
        with patch(
            "elite_trader.berserk_learning.get_suggestions",
            return_value={"berserk_learning_suggestions": {"win_rate": 55}},
        ), patch(
            "elite_trader.hunter_learning.get_suggestions",
            return_value={"hunter_learning_suggestions": {"liquidation_continuation_rate": 0.4}},
        ), patch(
            "elite_trader.chop_learning.get_suggestions",
            return_value={"chop_learning_suggestions": {"mean_reversion_success": 0.5}},
        ), patch(
            "elite_trader.sentinel_learning.snapshot_for_ui",
            return_value={"sentinel_benchmark_score": 60},
        ), patch(
            "elite_trader.sentinel_benchmark.get_dashboard",
            return_value={"safe_market_score": 70, "avoid_market_now": False},
        ):
            from elite_trader.evrim_meta_score import read_cross_mode_summaries

            s = read_cross_mode_summaries()
            self.assertIn("berserk", s)
            self.assertIn("hunter", s)
            self.assertEqual(s["berserk"].get("win_rate"), 55)

    def test_04_config_auto_apply_disabled_profile_unchanged(self, tmp_path=None):
        from elite_trader.evrim_config_pipeline import _SUGGESTIONS, propose_config_change

        prof_path = _ROOT / "data" / "mode_profiles.json"
        before = json.loads(prof_path.read_text(encoding="utf-8"))
        old_tp = before["modes"]["evrim"].get("tp_stake_pct")
        result = propose_config_change(
            {"tp_stake_pct": 0.0099},
            reason="test",
            source="unittest",
        )
        after = json.loads(prof_path.read_text(encoding="utf-8"))
        self.assertFalse(result.get("applied"))
        self.assertEqual(after["modes"]["evrim"].get("tp_stake_pct"), old_tp)
        self.assertTrue(_SUGGESTIONS.exists() or result.get("suggestion"))

    def test_05_expected_net_negative_veto(self):
        from elite_trader.evrim_risk_governor import assess_evrim_risk

        meta = {"final_score": 80, "expected_net_pnl_usd": -0.5}
        risk = assess_evrim_risk(
            {"symbol": "BTCUSDT"},
            {"expected_net_pnl": -0.5},
            _profile_v2(),
            meta,
            execution_path="live",
        )
        self.assertTrue(risk["risk_veto"])
        self.assertIn("expected_net_negative", risk["risk_reasons"])

    def test_06_sentinel_stop_new_entries_veto(self):
        from elite_trader.evrim_risk_governor import assess_evrim_risk

        meta = {
            "final_score": 80,
            "sentinel_risk_off": True,
            "sentinel_recommended_risk_mode": "stop_new_entries",
        }
        risk = assess_evrim_risk(
            {"symbol": "BTCUSDT"},
            {},
            _profile_v2(),
            meta,
            execution_path="live",
        )
        self.assertTrue(risk["risk_veto"])
        self.assertIn("sentinel_severe_risk_off", risk["risk_reasons"])

    def test_07_fee_gross_recovery_mode(self):
        from elite_trader.evrim_recovery import maybe_enter_recovery, reset_recovery

        reset_recovery()
        rec = maybe_enter_recovery({"fee_gross_ratio": 0.80}, {}, _profile_v2())
        self.assertTrue(rec.get("recovery_mode"))
        self.assertIn("fee_gross", rec.get("recovery_reason", ""))

    def test_08_daily_dd_halt_live(self):
        from elite_trader.evrim_risk_governor import assess_evrim_risk

        meta = {"final_score": 80}
        risk = assess_evrim_risk(
            {"symbol": "BTCUSDT"},
            {"daily_drawdown_pct": 13},
            _profile_v2(),
            meta,
            execution_path="live",
        )
        self.assertTrue(risk["risk_veto"])
        self.assertIn("daily_drawdown_halt", risk["risk_reasons"])

    def test_09_root_config_without_bt_not_applied(self):
        from elite_trader.evrim_config_pipeline import apply_approved_config, propose_config_change

        prop = propose_config_change(
            {"max_open": 15, "tp_stake_pct": 0.01},
            reason="root_change_test",
            source="unittest",
            backtest_passed=False,
        )
        sid = (prop.get("suggestion") or {}).get("id")
        self.assertTrue(sid)
        result = apply_approved_config(sid)
        self.assertFalse(result.get("ok"))
        self.assertEqual(result.get("error"), "backtest_required")

    def test_10_without_user_approval_config_unchanged(self):
        from elite_trader.mode_profiles import get_profile
        from elite_trader.evrim_config_pipeline import propose_config_change

        before = get_profile("evrim") or {}
        old_max = before.get("max_open")
        propose_config_change({"max_open": 99}, reason="no_approval", source="unittest")
        after = get_profile("evrim") or {}
        self.assertEqual(after.get("max_open"), old_max)

    def test_11_progress_to_2x_pct_computed(self):
        from elite_trader.evrim_progress_engine import compute_progress

        book = {
            "closed": [{"final_pnl": 100}, {"final_pnl": 50}],
            "open": [{"unrealized_pnl": 25}],
        }
        prog = compute_progress(book, _profile_v2(), session_start_balance=5000)
        self.assertIn("progress_to_2x_pct", prog)
        self.assertGreater(prog["current_equity"], 5000)
        self.assertEqual(prog["target_equity"], 10000)

    def test_12_exploration_paper_only_no_live(self):
        from elite_trader.evrim_exploration import assess_exploration, reset_exploration, touch_reject
        import time as _time

        reset_exploration()
        base = _time.time() - 25 * 60
        with patch("elite_trader.evrim_exploration._last_reject_ts", base), patch(
            "elite_trader.evrim_exploration._reject_count", 5
        ), patch("elite_trader.evrim_exploration._last_trade_ts", 0.0):
            exp = assess_exploration(_profile_v2(), now=base + 25 * 60)
            self.assertTrue(exp.get("exploration_mode"))
            self.assertTrue(exp.get("exploration_paper_only"))

        from elite_trader.evrim_v2 import evrim_v2_live_preflight

        ok, reason = evrim_v2_live_preflight(
            {"evrim_v2": {"exploration": exp}, "evrim_risk": {"risk_veto": False}}
        )
        self.assertFalse(ok)
        self.assertEqual(reason, "exploration_paper_only")


if __name__ == "__main__":
    unittest.main()
