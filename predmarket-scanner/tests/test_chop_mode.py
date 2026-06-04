"""Chop V2 — routing, regime, MR, trend guard, spread, learning, dashboard."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from elite_trader import futures_order_router as router
from elite_trader.chop_cooldown import check_cooldown, record_close, reset_stats
from elite_trader.chop_learning import get_suggestions, on_chop_trade_closed
from elite_trader.chop_metrics import build_chop_health
from elite_trader.mode_engines.chop_master_engine import evaluate
from elite_trader.mode_engines.chop_scoring import spread_assessment
from elite_trader.mode_profiles import get_profile
from elite_trader.order_gate import ORDER_ROUTE_LIVE, ORDER_ROUTE_PAPER, build_order_intent, route_order


def _profile() -> dict:
    return get_profile("chop_master") or {}


def _ctx(**kw):
    base = {
        "profile": _profile(),
        "spread_policy": "chop_tight",
        "adx": 18,
        "atr_pct": 0.15,
        "vol_ratio": 1.1,
        "near_vwap": True,
        "ema_tangled": True,
        "range_width_pct": 0.18,
        "regime": "chop",
        "spread_pct": 0.001,
        "mean_revert_bias": True,
    }
    base.update(kw)
    return base


def _signal(**kw):
    sig = {
        "change": -0.12,
        "strength": "Medium",
        "type": "LONG",
        "symbol": "ETHUSDT",
        "spread_pct": 0.001,
        "rsi7": 22,
        "range_low_rejection": True,
        "long_lower_wick": True,
        "wick_ratio": 0.5,
        "near_vwap": True,
        "mean_revert_bias": True,
        "candle_body_ratio": 0.25,
    }
    sig.update(kw)
    return sig


class TestChopRouting(unittest.TestCase):
    def test_paper_when_evrim_active(self):
        with patch.object(router, "_SAFE_MODE_PATH", Path("/tmp/chop_safe_test.json")):
            g = route_order(
                "chop_master",
                build_order_intent("chop_master", symbol="BTCUSDT", side="LONG"),
                active_futures_mode="evrim",
                api_healthy=True,
                live_orders_enabled=True,
            )
        self.assertEqual(g.order_route, ORDER_ROUTE_PAPER)
        self.assertFalse(g.send_live)

    def test_live_when_chop_active(self):
        with patch.object(router, "_SAFE_MODE_PATH", Path("/tmp/chop_safe_test2.json")):
            g = route_order(
                "chop_master",
                build_order_intent("chop_master", symbol="BTCUSDT", side="LONG"),
                active_futures_mode="chop_master",
                api_healthy=True,
                live_orders_enabled=True,
            )
        self.assertEqual(g.order_route, ORDER_ROUTE_LIVE)
        self.assertTrue(g.send_live)


class TestChopEngine(unittest.TestCase):
    def test_mean_reversion_candidate_at_65(self):
        sig = _signal()
        ok, reason = evaluate(sig, _ctx())
        self.assertTrue(ok, reason)
        meta = sig.get("chop_meta") or {}
        self.assertGreaterEqual(meta.get("chop_score", 0), 65)
        self.assertGreaterEqual(meta.get("mean_reversion_score", 0), 65)
        self.assertTrue(meta.get("mean_reversion_candidate"))

    def test_hunter_breakout_blocks_chop(self):
        sig = _signal()
        ok, reason = evaluate(sig, _ctx(hunter_breakout_score=78))
        self.assertFalse(ok)
        self.assertEqual(reason, "chop_trend_guard")
        meta = sig.get("chop_meta") or {}
        self.assertTrue(meta.get("trend_guard_active"))

    def test_range_too_narrow_blocks(self):
        sig = _signal()
        ok, reason = evaluate(sig, _ctx(range_width_pct=0.015))
        self.assertFalse(ok)
        self.assertEqual(reason, "chop_range_too_narrow")

    def test_spread_extreme_veto(self):
        info = spread_assessment(0.13, _profile())
        self.assertEqual(info["spread_risk_level"], "extreme")
        self.assertTrue(info["veto"])

    def test_trend_guard_blocks(self):
        sig = _signal()
        ok, reason = evaluate(sig, _ctx(ema_strong_aligned=True, adx=32, adx_rising=True))
        self.assertFalse(ok)
        self.assertEqual(reason, "chop_trend_guard")

    def test_paper_cooldown(self):
        reset_stats()
        record_close("ETHUSDT")
        ok, remaining, rejected = check_cooldown("ETHUSDT", 0.4)
        self.assertFalse(ok)
        self.assertTrue(rejected)
        self.assertGreater(remaining, 0)


class TestChopLearning(unittest.TestCase):
    def test_learning_no_profile_write(self):
        prof_path = _ROOT / "data" / "mode_profiles.json"
        before = prof_path.read_text(encoding="utf-8")
        sug_path = _ROOT / "data" / "backups" / "_test_chop_sug.json"
        sug_path.parent.mkdir(parents=True, exist_ok=True)
        with patch("elite_trader.chop_learning._SUGGESTIONS_PATH", sug_path):
            closed = []
            for i in range(50):
                row = {
                    "symbol": "BTCUSDT",
                    "final_pnl": 0.15 if i % 2 else -0.08,
                    "exit_reason": "TP",
                    "signal_strength": "Medium",
                    "spread_risk_level": "normal",
                    "chop_score": 72,
                    "mean_reversion_score": 68,
                    "range_width_pct": 0.16,
                    "duration": 8.0,
                    "total_fees": 0.06,
                }
                closed.append(row)
                on_chop_trade_closed(row, closed)
            sug = get_suggestions().get("chop_learning_suggestions") or {}
            self.assertIn("chop_quality_score", sug)
        after = prof_path.read_text(encoding="utf-8")
        self.assertEqual(before, after)


class TestChopDashboard(unittest.TestCase):
    def test_build_chop_health_keys(self):
        book = {
            "open": [],
            "closed": [
                {
                    "symbol": "ETHUSDT",
                    "final_pnl": 0.12,
                    "total_fees": 0.05,
                    "spread_risk_level": "normal",
                    "chop_score": 72,
                    "mean_reversion_score": 68,
                    "range_width_pct": 0.16,
                }
            ],
        }
        health = build_chop_health(book)
        for key in (
            "route_mode",
            "paper_trade_count",
            "chop_score_avg",
            "range_width_avg",
            "mean_reversion_success",
            "chop_learning_suggestions",
            "fee_gross_ratio",
            "trend_guard_count",
            "range_too_narrow_rejects",
        ):
            self.assertIn(key, health)


if __name__ == "__main__":
    unittest.main()
