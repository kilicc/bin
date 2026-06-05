"""Binance kapanış settlement — Transaction History ile hizalama."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from elite_trader.exchange_settlement import settle_position_close


class AvaxCloseSettlementTests(unittest.TestCase):
    def test_close_wallet_matches_binance_transaction_lines(self) -> None:
        """AVAX 17:19:42 — realized −9.954 + 0.055, exit comm ~3.993 → net ~−13.89."""

        class FakeClient:
            paper = False

            def user_trades(self, coin, order_id=None, start_ms=None, limit=100):
                if order_id == 99001:
                    return [
                        {
                            "orderId": "99001",
                            "side": "SELL",
                            "qty": "1117",
                            "price": "8.937",
                            "quoteQty": "9982.6",
                            "realizedPnl": "-9.954",
                            "commission": "3.95372880",
                            "time": 1780150782000,
                        },
                        {
                            "orderId": "99001",
                            "side": "SELL",
                            "qty": "5",
                            "price": "8.937",
                            "quoteQty": "44.7",
                            "realizedPnl": "0.055",
                            "commission": "0.03938440",
                            "time": 1780150782000,
                        },
                    ]
                return []

            def income_history(self, coin, start_ms=None):
                return [{"type": "COMMISSION", "income": "-7.95011320"}]

            def exchange_positions(self):
                return []

        pos = {
            "symbol": "AVAXUSDT",
            "side": "LONG",
            "on_exchange": True,
            "entry_price": 8.946,
            "size": 1117.0,
            "stake_usd": 1000.0,
            "opened_at_iso": "2026-05-30T14:19:00+00:00",
            "exchange_order_id": "88001",
        }
        with patch("elite_trader.exchange_settlement.time.sleep", lambda *_: None):
            settled = settle_position_close(
                FakeClient(),
                pos,
                close_order_id="99001",
                settle_wait_sec=0,
            )
        self.assertIsNotNone(settled)
        assert settled is not None
        self.assertAlmostEqual(float(settled["pnl_gross_usd"]), -9.899, places=2)
        self.assertAlmostEqual(float(settled["exit_fee"]), 3.9931132, places=2)
        self.assertAlmostEqual(float(settled["wallet_pnl"]), -13.892, places=1)
        self.assertNotAlmostEqual(float(settled["wallet_pnl"]), -17.89, places=1)


if __name__ == "__main__":
    unittest.main()
