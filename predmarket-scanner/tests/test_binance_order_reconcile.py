"""Binance -1007 emir timeout doğrulama."""
from __future__ import annotations

import unittest
from unittest import mock

from elite_trader.binance_order_reconcile import (
    is_order_timeout_error,
    recover_close_after_order_timeout,
)


class OrderTimeoutDetectTests(unittest.TestCase):
    def test_detects_code_1007(self) -> None:
        body = (
            '{"code":-1007,"msg":"Timeout waiting for response from backend server. '
            'Send status unknown; execution status unknown."}'
        )
        self.assertTrue(is_order_timeout_error(body))

    def test_ignores_other_errors(self) -> None:
        self.assertFalse(is_order_timeout_error('{"code":-2011,"msg":"Unknown order"}'))


class RecoverCloseAfterTimeoutTests(unittest.TestCase):
    def test_flat_position_settles(self) -> None:
        settled_payload = {
            "pnl_usd": 12.0,
            "wallet_pnl": 8.0,
            "fee_source": "binance_api",
            "pnl_source": "binance_api",
            "trade_count_close": 1,
            "exchange_close_order_id": "99001",
        }

        class FakeClient:
            paper = False

            def exchange_positions(self):
                return []

            def user_trades(self, coin, order_id=None, start_ms=None, limit=100):
                if order_id == 99001:
                    return [
                        {
                            "orderId": "99001",
                            "side": "SELL",
                            "qty": "10",
                            "price": "1",
                            "quoteQty": "10",
                            "realizedPnl": "12",
                            "commission": "4",
                            "time": 1000,
                        }
                    ]
                return [
                    {
                        "orderId": "99001",
                        "side": "SELL",
                        "qty": "10",
                        "price": "1",
                        "quoteQty": "10",
                        "realizedPnl": "12",
                        "commission": "4",
                        "time": 1000,
                    }
                ]

        pos = {
            "symbol": "AVAXUSDT",
            "side": "LONG",
            "on_exchange": True,
            "opened_at_iso": "2026-05-30T12:00:00+00:00",
            "size": 10.0,
        }

        with mock.patch(
            "elite_trader.exchange_settlement.settle_position_close",
            return_value=settled_payload,
        ), unittest.mock.patch(
            "elite_trader.exchange_settlement.settlement_has_api_close_fills",
            return_value=True,
        ), unittest.mock.patch(
            "elite_trader.binance_order_reconcile.time.sleep",
            lambda *_: None,
        ):
            settled, oid = recover_close_after_order_timeout(
                FakeClient(), pos, settle_wait_sec=0
            )
        self.assertIsNotNone(settled)
        self.assertEqual(oid, "99001")

    def test_still_open_returns_none(self) -> None:
        class FakeClient:
            paper = False

            def exchange_positions(self):
                return [
                    {
                        "symbol": "AVAXUSDT",
                        "side": "LONG",
                        "contracts": 100.0,
                    }
                ]

        pos = {
            "symbol": "AVAXUSDT",
            "side": "LONG",
            "on_exchange": True,
        }
        with mock.patch(
            "elite_trader.binance_order_reconcile.time.sleep",
            lambda *_: None,
        ):
            settled, oid = recover_close_after_order_timeout(
                FakeClient(), pos, settle_wait_sec=0
            )
        self.assertIsNone(settled)
        self.assertIsNone(oid)


if __name__ == "__main__":
    unittest.main()
