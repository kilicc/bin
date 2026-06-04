"""Berserk V2 — routing, spread, weak, fee survival, re-entry, learning, dashboard."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from elite_trader import futures_order_router as router
from elite_trader.berserk_cooldown import check_cooldown, record_close, reset_stats
from elite_trader.berserk_fee_survival import assess_fee_survival, record_trade_close, reset_session
from elite_trader.berserk_learning import get_suggestions, on_berserk_trade_closed
from elite_trader.berserk_metrics import build_berserk_health
from elite_trader.berserk_reentry import evaluate_reentry, record_close_result, reset_reentry_state
from elite_trader.mode_engines.berserk_engine import evaluate
from elite_trader.mode_engines.berserk_scoring import spread_assessment
from elite_trader.mode_profiles import get_profile
from elite_trader.order_gate import ORDER_ROUTE_LIVE, ORDER_ROUTE_PAPER, build_order_intent, route_order


def _profile() -> dict:
    return get_profile("berserk") or {}


def _ctx(**kw):
    base = {
        "profile": _profile(),
        "spread_policy": "dynamic_micro",
        "vol_ratio": 1.35,
        "orderbook_pressure": 0.6,
        "flow_bias": 1.0,
        "spread_pct": 0.04,
    }
    base.update(kw)
    return base


def _strong_signal(**kw) -> dict:
    sig = {
        "change": 0.18,
        "strength": "Weak",
        "type": "LONG",
        "symbol": "XRPUSDT",
        "vol_ratio": 1.35,
    }
    sig.update(kw)
    return sig


class TestBerserkRouting(unittest.TestCase):
    def test_paper_when_evrim_active(self):
        with patch.object(router, "_SAFE_MODE_PATH", Path("/tmp/berserk_safe_test.json")):
            g = route_order(
                "berserk",
                build_order_intent("berserk", symbol="BTCUSDT", side="LONG"),
                active_futures_mode="evrim",
                api_healthy=True,
                live_orders_enabled=True,
            )
        self.assertEqual(g.order_route, ORDER_ROUTE_PAPER)
        self.assertFalse(g.send_live)

    def test_live_when_active(self):
        with patch.object(router, "_SAFE_MODE_PATH", Path("/tmp/berserk_safe_test2.json")):
            g = route_order(
                "berserk",
                build_order_intent("berserk", symbol="BTCUSDT", side="LONG"),
                active_futures_mode="berserk",
                api_healthy=True,
                live_orders_enabled=True,
            )
        self.assertEqual(g.order_route, ORDER_ROUTE_LIVE)
        self.assertTrue(g.send_live)


class TestBerserkEngine(unittest.TestCase):
    def test_weak_signal_paper_entry(self):
        sig = _strong_signal(strength="Weak")
        ok, reason = evaluate(sig, _ctx())
        self.assertTrue(ok, reason)
        meta = sig.get("berserk_meta") or {}
        self.assertEqual(meta.get("strength_stake_mult"), 0.45)
        self.assertEqual(meta.get("learning_tag"), "weak_micro_test")

    def test_spread_extreme_veto(self):
        sig = {"change": 0.15, "strength": "Medium", "type": "LONG"}
        ok, reason = evaluate(sig, _ctx(spread_pct=0.15))
        self.assertFalse(ok)
        self.assertEqual(reason, "berserk_spread_extreme")

    def test_spread_soft_penalty_not_veto(self):
        info = spread_assessment(0.08, _profile())
        self.assertEqual(info["spread_risk_level"], "low")
        self.assertFalse(info["veto"])
        self.assertEqual(info["stake_mult"], 0.70)
        self.assertTrue(info.get("spread_penalty_applied"))

    def test_fee_recovery_mode(self):
        reset_session()
        prof = _profile()
        for _ in range(20):
            record_trade_close({"final_pnl": 0.02, "total_fees": 0.15, "spread_risk_level": "low"})
        state = assess_fee_survival(prof)
        self.assertTrue(state.get("recovery_mode"))
        self.assertEqual(state.get("fee_stake_mult"), 0.50)

    def test_revenge_reentry_blocked(self):
        reset_reentry_state()
        prof = _profile()
        record_close_result(
            "SOLUSDT",
            "LONG",
            exit_reason="SL",
            pnl=-1.0,
            profile=prof,
        )
        sig = _strong_signal(symbol="SOLUSDT", strength="Medium", berserk_score=50)
        ok, reason, meta = evaluate_reentry("SOLUSDT", "LONG", sig, _ctx(), prof)
        self.assertFalse(ok)
        self.assertEqual(reason, "revenge_trading_blocked")
        self.assertEqual(meta.get("reentry_fail_reason"), "revenge_trading_blocked")

    def test_paper_cooldown(self):
        reset_stats()
        record_close("ETHUSDT")
        ok, remaining, rejected = check_cooldown("ETHUSDT", 0.02)
        self.assertFalse(ok)
        self.assertTrue(rejected)
        self.assertGreater(remaining, 0)


class TestBerserkSlAutotune(unittest.TestCase):
    def test_autotune_every_three_sl(self):
        from elite_trader.berserk_sl_autotune import analyze_loss_trades
        from elite_trader.mode_profiles import get_profile

        prof = {
            **(get_profile("berserk") or {}),
            "berserk_sl_recover_sec": 90.0,
            "berserk_sl_min_age_sec": 120.0,
            "berserk_tp_grace_sec": 25.0,
        }
        batch = [
            {
                "symbol": "SUPERUSDT",
                "exit_reason": "SL",
                "final_pnl": -1.2,
                "duration": 90.0,
                "max_unreal_seen": 0.0,
                "min_unreal_seen": -1.5,
                "stake_usd": 120,
            },
            {
                "symbol": "AINUSDT",
                "exit_reason": "SL",
                "final_pnl": -0.4,
                "duration": 75.0,
                "max_unreal_seen": 0.7,
                "min_unreal_seen": -0.8,
                "stake_usd": 120,
            },
            {
                "symbol": "XRPUSDT",
                "exit_reason": "TP",
                "final_pnl": 0.5,
                "duration": 12.0,
                "max_unreal_seen": 0.6,
                "min_unreal_seen": -0.1,
                "stake_usd": 120,
            },
        ]
        analysis = analyze_loss_trades(batch, prof)
        self.assertGreaterEqual(analysis["loss_in_batch"], 2)
        self.assertIn("recover_cliff", analysis["patterns"])
        self.assertIn("peak_then_sl", analysis["patterns"])

    def test_autotune_stale_negative_pnl(self):
        from elite_trader.berserk_sl_autotune import analyze_loss_trades
        from elite_trader.mode_profiles import get_profile

        prof = get_profile("berserk") or {}
        batch = [
            {
                "symbol": "AINUSDT",
                "exit_reason": "STALE-RELEASE",
                "final_pnl": -0.02,
                "duration": 12.0,
                "max_unreal_seen": 0.70,
                "min_unreal_seen": -0.15,
                "stake_usd": 120,
                "total_fees": 0.19,
            },
            {
                "symbol": "BTCUSDT",
                "exit_reason": "STALE-DIP",
                "final_pnl": -0.08,
                "duration": 55.0,
                "max_unreal_seen": 0.0,
                "min_unreal_seen": -0.4,
                "stake_usd": 120,
            },
            {
                "symbol": "ETHUSDT",
                "exit_reason": "TP",
                "final_pnl": 0.40,
                "duration": 8.0,
                "max_unreal_seen": 0.5,
                "min_unreal_seen": 0.0,
                "stake_usd": 120,
            },
        ]
        analysis = analyze_loss_trades(batch, prof)
        self.assertEqual(analysis["loss_in_batch"], 2)
        self.assertIn("peak_then_loss", analysis["patterns"])
        self.assertIn("stale_early_release", analysis["patterns"])
        self.assertTrue(analysis["patch"])

    def test_cliff_stale_dip_before_sl(self):
        from datetime import datetime, timedelta, timezone

        from elite_trader.berserk_exit import berserk_stale_dip_exit

        prof = get_profile("berserk") or {}
        opened = (datetime.now(timezone.utc) - timedelta(seconds=82)).isoformat()
        reason = berserk_stale_dip_exit(
            opened_at=opened,
            unrealized_usd=-0.35,
            sl_target_usd=0.29,
            stake_usd=120,
            min_unreal_seen=-0.9,
            leverage=5,
            profile={
                **prof,
                "berserk_sl_recover_sec": 90,
                "berserk_sl_min_age_sec": 120,
                "berserk_sl_cliff_preempt_sec": 12,
                "berserk_stale_dip_min_age_sec": 50,
            },
        )
        self.assertEqual(reason, "STALE-DIP")


class TestBerserkLearning(unittest.TestCase):
    def test_learning_no_profile_write(self):
        prof_path = _ROOT / "data" / "mode_profiles.json"
        before = prof_path.read_text(encoding="utf-8")
        sug_path = _ROOT / "data" / "backups" / "_test_berserk_sug.json"
        sug_path.parent.mkdir(parents=True, exist_ok=True)
        with patch("elite_trader.berserk_learning._SUGGESTIONS_PATH", sug_path):
            closed = []
            for i in range(100):
                row = {
                    "symbol": "BTCUSDT",
                    "final_pnl": 0.5 if i % 2 else -0.3,
                    "exit_reason": "TP",
                    "signal_strength": "Weak",
                    "spread_risk_level": "none",
                    "min_stake_source": "mode_profile",
                    "duration": 12.0,
                    "total_fees": 0.08,
                }
                closed.append(row)
                on_berserk_trade_closed(row, closed)
            sug = get_suggestions().get("berserk_learning_suggestions") or {}
            self.assertIn("suggested_min_score", sug)
        after = prof_path.read_text(encoding="utf-8")
        self.assertEqual(before, after)


class TestBerserkDashboard(unittest.TestCase):
    def test_build_health_metrics(self):
        book = {
            "open": [],
            "closed": [
                {
                    "symbol": "BTCUSDT",
                    "final_pnl": 0.4,
                    "exit_reason": "TP",
                    "signal_strength": "Weak",
                    "spread_risk_level": "none",
                    "duration": 8.0,
                    "total_fees": 0.06,
                    "learning_tag": "weak_micro_test",
                }
            ],
        }
        h = build_berserk_health(book)
        self.assertIn(h["route_mode"], ("paper", "live"))
        self.assertIn("fee_gross_ratio", h)
        self.assertIn("reentry_count", h)
        self.assertIn("berserk_learning_suggestions", h)
        self.assertEqual(h["weak_entry_count"], 1)


class TestBerserkStake(unittest.TestCase):
    def test_min_stake_source(self):
        from elite_trader.mode_engines.berserk_scoring import resolve_min_stake

        stake, src = resolve_min_stake(_profile(), paper=True, env_min=200)
        self.assertEqual(stake, 120)
        self.assertEqual(src, "mode_profile_paper_scaled")

    def test_paper_weak_stake_floor(self):
        from elite_trader.mode_engines.berserk_scoring import resolve_min_stake

        stake, _src = resolve_min_stake(
            _profile(), paper=True, env_min=80, strength_mult=0.45
        )
        self.assertAlmostEqual(stake, 54.0)


if __name__ == "__main__":
    unittest.main()
