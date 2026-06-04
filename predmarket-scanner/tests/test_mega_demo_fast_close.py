"""MEGA demo +$30 hızlı kapanış yolu."""
from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from elite_trader import mega_live as ml


class MegaDemoFastCloseTests(unittest.TestCase):
    def setUp(self) -> None:
        self._env = patch.dict(
            os.environ,
            {
                "MEGA_DEMO_FAST_CLOSE": "1",
                "MEGA_BINANCE_FUTURES_DEMO": "1",
                "MEGA_DEMO_FAST_CLOSE_GROSS_USD": "30",
            },
            clear=False,
        )
        self._env.start()

    def tearDown(self) -> None:
        self._env.stop()

    def test_eligible_at_30_gross(self) -> None:
        pos = {
            "on_exchange": True,
            "exchange_unrealized_pnl": 31.5,
            "entry_price": 10.0,
            "mark_price": 10.5,
            "side": "LONG",
            "symbol": "INJUSDT",
        }
        mc = type("MC", (), {"paper": False})()
        self.assertTrue(ml._mega_demo_fast_close_eligible(pos, mc))
        ok, _ = ml._mega_demo_fast_close_price_ok(pos, mc)
        self.assertTrue(ok)
        self.assertTrue(ml._mega_arm_demo_fast_close(pos, mc))
        self.assertTrue(pos.get("demo_fast_close"))

    def test_price_rejects_wrong_side(self) -> None:
        pos = {
            "on_exchange": True,
            "exchange_unrealized_pnl": 35.0,
            "entry_price": 10.0,
            "mark_price": 9.5,
            "side": "LONG",
            "symbol": "INJUSDT",
        }
        ok, detail = ml._mega_demo_fast_close_price_ok(pos, None)
        self.assertFalse(ok)
        self.assertIn("mark", detail)


if __name__ == "__main__":
    unittest.main()
