"""TP-TIMER — yalnızca book fill net > min; mark fallback yok."""
from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


class TpTimerFillGateTests(unittest.TestCase):
    def test_tp_timer_requires_fill_net_ready(self):
        from elite_trader.position_rescue import tp_timer_exit_reason

        pos = {
            "symbol": "LINKUSDT",
            "side": "SHORT",
            "stake_usd": 120,
            "leverage": 4,
            "unrealized_pnl": 0.27,
            "entry_time": 0,
            "on_exchange": True,
        }
        client = MagicMock(paper=False)

        with patch(
            "elite_trader.position_rescue._position_age_sec", return_value=900.0
        ), patch(
            "elite_trader.exchange_fill_truth.fill_net_close_ready",
            return_value=(False, 0.25, 0.40, {}),
        ) as mock_ready:
            self.assertIsNone(
                tp_timer_exit_reason(pos, mode_id="berserk2", client=client)
            )
            mock_ready.assert_called_once()

    def test_tp_timer_no_mark_fallback_when_fill_fails(self):
        from elite_trader.position_rescue import tp_timer_exit_reason

        pos = {
            "symbol": "LINKUSDT",
            "side": "SHORT",
            "stake_usd": 120,
            "leverage": 4,
            "unrealized_pnl": 0.80,
            "entry_fee": 0.19,
            "on_exchange": True,
        }
        client = MagicMock(paper=False)

        with patch(
            "elite_trader.position_rescue._position_age_sec", return_value=900.0
        ), patch(
            "elite_trader.exchange_fill_truth.fill_net_close_ready",
            return_value=(False, -0.10, 0.40, {}),
        ):
            self.assertIsNone(
                tp_timer_exit_reason(pos, mode_id="berserk2", client=client)
            )

    def test_fill_gross_rejects_stale_book_vs_mark(self):
        from elite_trader.exchange_fill_truth import fill_gross_sane_vs_mark

        pos = {"unrealized_pnl": 0.27, "stake_usd": 120}
        est = {"fill_gross": 6.65, "mark_unreal": 0.27}
        self.assertFalse(fill_gross_sane_vs_mark(est, pos))

    def test_fill_gross_allows_normal_spread_to_mark(self):
        from elite_trader.exchange_fill_truth import fill_gross_sane_vs_mark

        pos = {"unrealized_pnl": 0.50, "stake_usd": 120}
        est = {"fill_gross": 0.55, "mark_unreal": 0.50}
        self.assertTrue(fill_gross_sane_vs_mark(est, pos))


if __name__ == "__main__":
    unittest.main()
