"""Settlement — yanlış TP orderId, gerçek SL fill."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from elite_trader.exchange_settlement import settle_position_close


class ExchangeSettlementSlOidTests(unittest.TestCase):
    def test_falls_back_to_latest_closing_trades(self) -> None:
        client = MagicMock()
        client.paper = False
        opened_ms = 1_700_000_000_000
        pos = {
            "symbol": "APTUSDT",
            "side": "SHORT",
            "on_exchange": True,
            "entry_price": 0.84,
            "size": 8000.0,
            "stake_usd": 700.0,
            "exchange_order_id": "111",
            "opened_at_iso": "2026-06-03T19:13:10+00:00",
        }
        sl_fill = {
            "orderId": "999",
            "side": "BUY",
            "qty": "8000",
            "price": "0.8315",
            "quoteQty": "6652",
            "realizedPnl": "-0.55",
            "commission": "0.19",
            "time": opened_ms + 360_000,
        }

        def user_trades(coin, order_id=None, start_ms=None, limit=100):
            if order_id == 555:
                return []
            if order_id == 111:
                return []
            if start_ms:
                return [sl_fill]
            return []

        client.user_trades = user_trades
        client.exchange_positions.return_value = []

        with patch.dict("os.environ", {"ELITE_EXCHANGE_TRUTH": "1"}, clear=False):
            with patch(
                "elite_trader.exchange_settlement.fetch_close_fees_from_client",
                return_value={"income_commission": 0, "income_funding": 0},
            ):
                with patch(
                    "elite_trader.income_close.aggregate_close_income_at_ms",
                    return_value=None,
                ):
                    settled = settle_position_close(
                        client,
                        pos,
                        close_order_id="555",
                        settle_wait_sec=0,
                    )
        self.assertIsNotNone(settled)
        self.assertEqual(settled.get("trade_count_close"), 1)
        self.assertAlmostEqual(float(settled.get("wallet_pnl") or 0), -0.74, places=1)


if __name__ == "__main__":
    unittest.main()
