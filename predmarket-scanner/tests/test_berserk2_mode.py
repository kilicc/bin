"""BERSERK2 — top10 gate, BTC veto, registry."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from elite_trader.berserk2_btc_context import get_btc_context
from elite_trader.berserk2_movers import is_top_mover, refresh_top_movers
from elite_trader.mode_engines.berserk2_engine import evaluate
from elite_trader.mode_profiles import get_profile
from elite_trader.mode_registry import MODE_IDS, is_berserk_family, is_valid_mode


def _profile() -> dict:
    return get_profile("berserk2") or {}


def _ctx(**kw):
    base = {
        "profile": _profile(),
        "spread_policy": "dynamic_micro",
        "vol_ratio": 1.4,
        "orderbook_pressure": 0.55,
        "flow_bias": 1.0,
        "spread_pct": 0.04,
        "btc_regime": "trend_up",
        "btc_24h_change": 1.2,
        "btc_context": {"btc_regime": "trend_up", "btc_24h_change": 1.2},
    }
    base.update(kw)
    return base


def _signal(**kw):
    sig = {
        "change": 0.15,
        "strength": "Medium",
        "type": "LONG",
        "symbol": "SOLUSDT",
        "vol_ratio": 1.4,
    }
    sig.update(kw)
    return sig


class TestBerserk2Registry(unittest.TestCase):
    def test_mode_registered(self):
        self.assertIn("berserk2", MODE_IDS)
        self.assertTrue(is_valid_mode("berserk2"))
        self.assertTrue(is_berserk_family("berserk2"))

    def test_profile_loads(self):
        p = _profile()
        self.assertEqual(p.get("berserk2_top_n"), 10)
        self.assertGreater(float(p.get("min_stake_usd") or 0), 0)


class TestBerserk2Movers(unittest.TestCase):
    def test_top10_gate(self):
        hist: dict = {
            "SOLUSDT": [
                {"price": 100.0},
                {"price": 100.5},
                {"price": 101.2},
            ],
            "XRPUSDT": [{"price": 0.5}, {"price": 0.51}, {"price": 0.52}],
        }
        prices = {"SOLUSDT": 102.0, "XRPUSDT": 0.53, "ADAUSDT": 0.4}
        refresh_top_movers(
            ["SOLUSDT", "XRPUSDT", "ADAUSDT"],
            prices,
            hist,
            top_n=2,
        )
        self.assertTrue(is_top_mover("SOLUSDT"))
        self.assertFalse(is_top_mover("ADAUSDT"))


class TestBerserk2BtcGate(unittest.TestCase):
    def test_long_soft_btc_trend_down(self):
        refresh_top_movers(
            ["SOLUSDT"],
            {"SOLUSDT": 100.0},
            {"SOLUSDT": [{"price": 99}, {"price": 99.5}, {"price": 100}, {"price": 100.5}]},
            top_n=1,
        )
        sig = _signal(type="LONG", symbol="SOLUSDT", change=0.12)
        ctx = _ctx(btc_regime="trend_down", btc_context={"btc_regime": "trend_down"})
        ok, reason = evaluate(sig, ctx)
        if ok:
            self.assertIn(sig.get("berserk_meta", {}).get("btc_entry_tag", ""), ("", "berserk2_btc_long_soft"))
        else:
            self.assertIn(reason, ("berserk_score_low", "berserk_min_move", "berserk_spread_extreme"))

    def test_not_top_mover(self):
        sig = _signal(symbol="DOGEUSDT")
        ok, reason = evaluate(sig, _ctx())
        self.assertFalse(ok)
        self.assertEqual(reason, "berserk2_not_top_mover")


class TestBerserk2BtcContext(unittest.TestCase):
    def test_snapshot_keys(self):
        snap = get_btc_context()
        self.assertIn("btc_regime", snap)


if __name__ == "__main__":
    unittest.main()
