"""Hunter V2 — routing, spread, breakout, chop, cooldown, learning, dashboard."""
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
from elite_trader.hunter_cooldown import check_cooldown, record_close, reset_stats
from elite_trader.hunter_learning import get_suggestions, on_hunter_trade_closed
from elite_trader.hunter_metrics import build_hunter_health
from elite_trader.hunter_watchlist import watchlist_size
from elite_trader.mode_engines.hunter_engine import evaluate
from elite_trader.mode_engines.hunter_scoring import spread_assessment
from elite_trader.mode_profiles import get_profile
from elite_trader.order_gate import ORDER_ROUTE_LIVE, ORDER_ROUTE_PAPER, build_order_intent, route_order


def _profile() -> dict:
    return get_profile("hunter") or {}


def _ctx(**kw):
    base = {
        "profile": _profile(),
        "spread_policy": "hunter_medium_penalty",
        "vol_ratio": 1.4,
        "liquidation_proxy": 0.35,
        "orderbook_pressure": 0.25,
        "flow_bias": 1.0,
        "regime": "trend",
    }
    base.update(kw)
    return base


def _signal(**kw):
    sig = {
        "change": 0.32,
        "strength": "Medium",
        "type": "LONG",
        "symbol": "ETHUSDT",
        "spread_pct": 0.05,
        "signal_age_sec": 4.0,
    }
    sig.update(kw)
    return sig


class TestHunterRouting(unittest.TestCase):
    def test_paper_when_evrim_active(self):
        with patch.object(router, "_SAFE_MODE_PATH", Path("/tmp/hunter_safe_test.json")):
            g = route_order(
                "hunter",
                build_order_intent("hunter", symbol="BTCUSDT", side="LONG"),
                active_futures_mode="evrim",
                api_healthy=True,
                live_orders_enabled=True,
            )
        self.assertEqual(g.order_route, ORDER_ROUTE_PAPER)
        self.assertFalse(g.send_live)

    def test_live_when_active(self):
        with patch.object(router, "_SAFE_MODE_PATH", Path("/tmp/hunter_safe_test2.json")):
            g = route_order(
                "hunter",
                build_order_intent("hunter", symbol="BTCUSDT", side="LONG"),
                active_futures_mode="hunter",
                api_healthy=True,
                live_orders_enabled=True,
            )
        self.assertEqual(g.order_route, ORDER_ROUTE_LIVE)
        self.assertTrue(g.send_live)
        self.assertFalse(g.allow_binance_send)


class TestHunterEngine(unittest.TestCase):
    def test_weak_signal_watch_only_not_trade(self):
        sig = {
            "change": 0.28,
            "strength": "Weak",
            "type": "LONG",
            "symbol": "XRPUSDT",
            "spread_pct": 0.05,
            "signal_age_sec": 4.0,
        }
        ok, reason = evaluate(sig, _ctx())
        self.assertFalse(ok)
        self.assertEqual(reason, "weak_watch_only")
        self.assertGreaterEqual(watchlist_size(), 1)

    def test_medium_signal_paper_entry(self):
        sig = _signal()
        ok, reason = evaluate(sig, _ctx())
        self.assertTrue(ok, reason)
        meta = sig.get("hunter_meta") or {}
        self.assertEqual(meta.get("strength_stake_mult"), 0.70)
        self.assertGreaterEqual(meta.get("breakout_score", 0), 55)

    def test_strong_breakout_logged(self):
        sig = _signal(
            change=0.50,
            strength="Strong",
            symbol="SOLUSDT",
            spread_pct=0.04,
            signal_age_sec=5.0,
        )
        ok, reason = evaluate(sig, _ctx(vol_ratio=1.6, liquidation_proxy=0.5))
        self.assertTrue(ok, reason)
        meta = sig.get("hunter_meta") or {}
        self.assertGreaterEqual(meta.get("breakout_score", 0), 70)
        self.assertEqual(meta.get("breakout_tier"), "strong")

    def test_fake_breakout_risk_blocks_at_75(self):
        sig = _signal(
            change=0.38,
            symbol="DOGEUSDT",
            spread_pct=0.12,
            wick_ratio=0.65,
            signal_age_sec=4.0,
        )
        ok, reason = evaluate(sig, _ctx(vol_ratio=1.05, orderbook_pressure=-0.4))
        self.assertFalse(ok)
        self.assertEqual(reason, "fake_breakout_risk")
        meta = sig.get("hunter_meta") or {}
        self.assertGreaterEqual(meta.get("fake_breakout_risk", 0), 75)

    def test_chop_observation_not_trade(self):
        sig = _signal()
        ok, reason = evaluate(sig, _ctx(regime="chop"))
        self.assertFalse(ok)
        self.assertEqual(reason, "hunter_chop_observation")
        meta = sig.get("hunter_meta") or {}
        self.assertTrue(meta.get("hunter_chop_observation"))

    def test_spread_extreme_veto(self):
        info = spread_assessment(0.20, _profile())
        self.assertEqual(info["spread_risk_level"], "extreme")
        self.assertTrue(info["veto"])

    def test_spread_soft_penalty_not_veto(self):
        info = spread_assessment(0.10, _profile())
        self.assertEqual(info["spread_risk_level"], "elevated")
        self.assertFalse(info["veto"])
        self.assertEqual(info["stake_mult"], 0.70)

    def test_paper_cooldown_simulation(self):
        reset_stats()
        record_close("ETHUSDT")
        ok, remaining, rejected = check_cooldown("ETHUSDT", 0.8)
        self.assertFalse(ok)
        self.assertGreater(remaining, 0)
        self.assertTrue(rejected)


class TestHunterLearning(unittest.TestCase):
    def test_learning_suggestions_no_profile_write(self):
        with patch("elite_trader.hunter_learning._SUGGESTIONS_PATH") as sug_path:
            with patch("elite_trader.mode_profiles._PROFILES_PATH", create=True) as prof_path:
                tmp = Path("/tmp/hunter_learn_test")
                tmp.mkdir(parents=True, exist_ok=True)
                pfile = tmp / "mode_profiles.json"
                sfile = tmp / "hunter_learning_suggestions.json"
                pfile.write_text(
                    json.dumps({"modes": {"hunter": _profile()}}),
                    encoding="utf-8",
                )
                sug_path.__str__ = lambda: str(sfile)
                sug_path.parent = tmp
                prof_path.__str__ = lambda: str(pfile)

                import elite_trader.hunter_learning as hl

                hl._SUGGESTIONS_PATH = sfile
                before = json.loads(pfile.read_text(encoding="utf-8"))
                closed = []
                for i in range(50):
                    row = {
                        "symbol": "BTCUSDT",
                        "final_pnl": 0.5 if i % 2 else -0.3,
                        "exit_reason": "TP",
                        "signal_strength": "Medium",
                        "spread_risk_level": "normal",
                        "breakout_score": 72,
                        "duration": 12.0,
                    }
                    closed.append(row)
                    on_hunter_trade_closed(row, closed)
                after = json.loads(pfile.read_text(encoding="utf-8"))
                self.assertEqual(before, after)
                self.assertTrue(get_suggestions().get("hunter_learning_suggestions"))


class TestHunterDashboard(unittest.TestCase):
    def test_build_hunter_health_keys(self):
        book = {
            "open": [],
            "closed": [
                {
                    "symbol": "BTCUSDT",
                    "final_pnl": 1.2,
                    "total_fees": 0.15,
                    "spread_risk_level": "normal",
                    "breakout_score": 72,
                    "change": 0.35,
                }
            ],
        }
        health = build_hunter_health(book)
        for key in (
            "route_mode",
            "paper_trade_count",
            "breakout_score_avg",
            "missed_explosive_moves",
            "hunter_learning_suggestions",
            "spread_risk_distribution",
            "avg_win_avg_loss_ratio",
            "fee_gross_ratio",
        ):
            self.assertIn(key, health)


if __name__ == "__main__":
    unittest.main()
