"""MEGA direction guard — BTC bear, vol side, cluster."""
from __future__ import annotations

import os
import time
import unittest
from unittest.mock import patch

from elite_trader import mega_direction_guard as dg


def _hist(prices: list[float]) -> list[dict]:
    return [{"price": p, "time": "12:00:00"} for p in prices]


class MegaDirectionGuardTests(unittest.TestCase):
    def test_btc_context_unknown_blocks_entry(self) -> None:
        with patch.object(
            dg,
            "btc_context_extended",
            return_value={"btc_regime": "unknown", "updated_at": 1e9, "btc_price": 67000},
        ):
            ok, tag = dg.mega_entry_allowed({"symbol": "ETHUSDT", "type": "SHORT"})
        self.assertFalse(ok)
        self.assertEqual(tag, "btc_regime_unknown")

    def test_btc_context_stale_blocks_entry(self) -> None:
        with patch.object(
            dg,
            "btc_context_extended",
            return_value={
                "btc_regime": "trend_down",
                "updated_at": 1.0,
                "btc_price": 67000,
            },
        ):
            with patch.object(dg, "btc_context_max_age_sec", return_value=60.0):
                ok, tag = dg.mega_entry_allowed({"symbol": "ETHUSDT", "type": "SHORT"})
        self.assertFalse(ok)
        self.assertEqual(tag, "btc_context_stale")

    def test_btc_bearish_trend_down(self) -> None:
        with patch.object(dg, "get_btc_context", return_value={"btc_regime": "trend_down"}):
            bear, tag = dg.btc_bearish({})
        self.assertTrue(bear)
        self.assertEqual(tag, "btc_trend_down")

    def test_vol_scan_blocks_long_in_bear_bounce(self) -> None:
        ph = {
            "ETHUSDT": _hist([100.0] * 10 + [100.5, 100.55, 100.6]),
        }
        with patch.object(dg, "btc_context_ready", return_value=(True, "")):
            with patch.object(dg, "btc_bearish", return_value=(True, "btc_trend_down")):
                side, reason = dg.resolve_vol_scan_side(
                    "ETHUSDT", 0.05, ph, min_abs_pct=0.002
                )
        self.assertIsNone(side)
        self.assertIn("btc", reason)

    def test_vol_scan_short_on_medium_bear(self) -> None:
        base = [100.0 - i * 0.08 for i in range(16)]
        ph = {"SOLUSDT": _hist(base + [98.5, 98.45])}
        with patch.object(dg, "btc_context_ready", return_value=(True, "")):
            with patch.object(dg, "btc_bearish", return_value=(False, "")):
                side, _ = dg.resolve_vol_scan_side("SOLUSDT", -0.04, ph, min_abs_pct=0.002)
        self.assertEqual(side, "SHORT")

    def test_cluster_blocks_when_enabled_and_cap_reached(self) -> None:
        fake_pos = [
            {"side": "LONG", "entry_time": 1.0},
            {"side": "LONG", "entry_time": 2.0},
        ]
        env = {
            "MEGA_CLUSTER_GUARD": "1",
            "MEGA_CLUSTER_BEAR_ONLY": "0",
            "MEGA_CLUSTER_MAX_SAME_SIDE": "2",
            "MEGA_CLUSTER_OPEN_ONLY": "1",
        }
        with patch.dict(os.environ, env, clear=False):
            import elite_trader.mega_live as ml

            with patch.object(ml, "_mega_positions", fake_pos):
                ok, tag = dg.cluster_allows_side("LONG")
        self.assertFalse(ok)
        self.assertIn("cluster", tag)

    def test_cluster_off_by_default(self) -> None:
        env = {"MEGA_CLUSTER_GUARD": "0"}
        with patch.dict(os.environ, env, clear=False):
            import elite_trader.mega_live as ml

            with patch.object(
                ml,
                "_mega_positions",
                [{"side": "LONG"}, {"side": "LONG"}, {"side": "LONG"}],
            ):
                ok, _ = dg.cluster_allows_side("LONG")
        self.assertTrue(ok)

    def test_mega_entry_blocks_long_when_btc_bear(self) -> None:
        sig = {"symbol": "LINKUSDT", "type": "LONG", "change": 0.1}
        with patch.object(dg, "btc_context_ready", return_value=(True, "")):
            with patch.object(dg, "btc_bearish", return_value=(True, "btc_24h_bear")):
                with patch(
                    "elite_trader.btc_macro_feed.macro_entry_allowed",
                    return_value=(True, ""),
                ):
                    ok, tag = dg.mega_entry_allowed(sig, price_history={})
        self.assertFalse(ok)
        self.assertEqual(tag, "btc_24h_bear")


if __name__ == "__main__":
    unittest.main()
