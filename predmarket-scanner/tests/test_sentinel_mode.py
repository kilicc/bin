"""Sentinel V2 — routing, kalite, execution, spread, cooldown, öğrenme, benchmark."""
from __future__ import annotations

import json
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


class TestSentinelRouting(unittest.TestCase):
    def test_paper_when_not_active_futures(self):
        from elite_trader.order_gate import ORDER_ROUTE_PAPER, route_order

        r = route_order(
            "sentinel",
            {"symbol": "BTCUSDT", "side": "LONG"},
            active_futures_mode="evrim",
            live_orders_enabled=True,
        )
        self.assertEqual(r.order_route, ORDER_ROUTE_PAPER)
        self.assertFalse(r.send_live)

    def test_live_when_active_sentinel(self):
        from elite_trader.order_gate import ORDER_ROUTE_LIVE, route_order

        r = route_order(
            "sentinel",
            {"symbol": "BTCUSDT", "side": "LONG", "expected_net_pnl": 0.5},
            active_futures_mode="sentinel",
            live_orders_enabled=True,
            api_healthy=True,
        )
        self.assertEqual(r.order_route, ORDER_ROUTE_LIVE)
        self.assertTrue(r.send_live)


class TestSentinelEngine(unittest.TestCase):
    def _profile(self) -> dict:
        return {
            "min_stake_usd": 180,
            "tp_stake_pct": 0.0095,
            "sl_stake_pct": 0.0042,
            "tp_trigger_frac": 1.02,
            "sentinel_min_quality_score": 62,
            "sentinel_allow_medium_if_quality": True,
            "sentinel_news_risk_mode": "risk_off",
            "sentinel_trend_misalignment_mode": "veto",
            "medium_stake_multiplier": 0.60,
            "strong_stake_multiplier": 1.00,
            "entry_stake_mult": 0.9,
            "max_spread_pct": 0.12,
            "soft_spread_start_pct": 0.08,
        }

    def test_weak_observation_no_trade(self):
        from elite_trader.mode_engines.sentinel_engine import evaluate

        sig = {"symbol": "ETHUSDT", "type": "LONG", "strength": "Weak", "change": 0.02}
        ok, reason = evaluate(sig, {"profile": self._profile(), "regime": "trend"})
        self.assertFalse(ok)
        self.assertEqual(reason, "sentinel_weak_observation")
        meta = sig.get("sentinel_meta") or {}
        self.assertIn("sentinel_quality_score", meta)

    def test_medium_with_quality_opens(self):
        from elite_trader.mode_engines.sentinel_engine import evaluate

        sig = {
            "symbol": "ETHUSDT",
            "type": "LONG",
            "strength": "Medium",
            "change": 0.55,
            "spread_pct": 0.05,
            "trend_bias": "LONG",
            "vol_ratio": 1.5,
            "adx": 24,
        }
        ctx = {
            "profile": self._profile(),
            "regime": "trend",
            "trend_bias": "LONG",
            "vol_ratio": 1.5,
            "adx": 24,
            "spread_pct": 0.05,
        }
        ok, reason = evaluate(sig, ctx)
        self.assertTrue(ok, reason)
        self.assertGreaterEqual(sig.get("sentinel_quality_score", 0), 62)

    def test_high_quality_candidate_logged(self):
        from elite_trader.mode_engines.sentinel_engine import evaluate

        sig = {
            "symbol": "SOLUSDT",
            "type": "LONG",
            "strength": "Strong",
            "change": 0.85,
            "spread_pct": 0.03,
            "trend_bias": "LONG",
            "vol_ratio": 1.8,
            "adx": 30,
        }
        ctx = {
            "profile": self._profile(),
            "regime": "trend",
            "trend_bias": "LONG",
            "vol_ratio": 1.8,
            "adx": 30,
            "spread_pct": 0.03,
        }
        ok, _ = evaluate(sig, ctx)
        self.assertTrue(ok)
        self.assertGreaterEqual(sig.get("sentinel_quality_score", 0), 75)
        meta = sig.get("sentinel_meta") or {}
        self.assertEqual(meta.get("sentinel_quality_tier"), "high_quality")
        self.assertIn("quality_breakdown", meta)

    def test_execution_quality_blocks(self):
        from elite_trader.mode_engines.sentinel_scoring import (
            calculate_execution_quality_score,
            calculate_sentinel_quality_score,
        )

        profile = self._profile()
        sig = {"symbol": "XRPUSDT", "type": "LONG", "strength": "Strong", "change": 0.6}
        ctx = {"spread_pct": 0.25, "vol_ratio": 0.5, "api_latency_ms": 5000}
        q = calculate_sentinel_quality_score(sig, ctx, profile)
        ex = calculate_execution_quality_score(sig, ctx, profile, q)
        self.assertLess(ex["sentinel_execution_quality_score"], 70)

    def test_spread_veto(self):
        from elite_trader.mode_engines.sentinel_scoring import evaluate_sentinel_spread

        meta = evaluate_sentinel_spread(0.15, 180, self._profile())
        self.assertTrue(meta["spread_veto"])


class TestSentinelCooldown(unittest.TestCase):
    def test_paper_cooldown_rejects(self):
        from elite_trader import sentinel_cooldown as sc

        sc._last_close.clear()
        sc._reject_count = 0
        sc.record_close("BTCUSDT")
        ok, rem, rej = sc.check_cooldown("BTCUSDT", 3.0)
        self.assertFalse(ok)
        self.assertTrue(rej)
        self.assertGreater(rem, 0)


class TestSentinelLearning(unittest.TestCase):
    def test_learning_does_not_write_profile(self):
        from elite_trader.sentinel_learning import on_trade_closed

        prof_path = _ROOT / "data" / "mode_profiles.json"
        before = prof_path.read_text(encoding="utf-8")
        closed = [
            {
                "symbol": f"COIN{i}USDT",
                "final_pnl": 1.0 if i % 2 else -0.5,
                "sentinel_meta": {"sentinel_quality_score": 70 + i % 5},
            }
            for i in range(30)
        ]
        out = on_trade_closed(closed)
        self.assertIsNotNone(out)
        self.assertIn("quality_signal_rank", out)
        after = prof_path.read_text(encoding="utf-8")
        self.assertEqual(before, after)


class TestSentinelBenchmark(unittest.TestCase):
    def test_benchmark_every_100_decisions(self):
        from elite_trader import sentinel_benchmark as sb

        sb.reset_session_stats()
        sig = {
            "symbol": "BTCUSDT",
            "type": "LONG",
            "strength": "Medium",
            "change": 0.4,
            "sentinel_meta": {"sentinel_quality_score": 68, "sentinel_safe_market_score": 70},
        }
        for _ in range(100):
            sb.on_sentinel_decision(sig, allowed=False, reason="sentinel_watch")
        bench_path = _ROOT / "data" / "sentinel_benchmark.json"
        self.assertTrue(bench_path.is_file())
        data = json.loads(bench_path.read_text(encoding="utf-8"))
        self.assertIn("sentinel_benchmark", data)
        bench = data["sentinel_benchmark"]
        self.assertIn("sentinel_quality_index", bench)
        self.assertIn("avoid_market_now", bench)


class TestSentinelDashboard(unittest.TestCase):
    def test_build_sentinel_health_keys(self):
        from elite_trader.sentinel_metrics import build_sentinel_health

        book = {
            "open": [],
            "closed": [
                {
                    "symbol": "ETHUSDT",
                    "final_pnl": 0.8,
                    "total_fees": 0.12,
                    "sentinel_meta": {
                        "sentinel_quality_score": 78,
                        "sentinel_execution_quality_score": 82,
                        "sentinel_signal_tags": ["high_quality_trend"],
                    },
                }
            ],
        }
        health = build_sentinel_health(book)
        for key in (
            "route_mode",
            "sentinel_quality_score_avg",
            "safe_market_score",
            "sentinel_benchmark",
            "sentinel_learning_suggestions",
            "execution_quality_avg",
        ):
            self.assertIn(key, health)


if __name__ == "__main__":
    unittest.main()
