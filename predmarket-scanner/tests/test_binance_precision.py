"""Binance LOT_SIZE / MARKET_LOT_SIZE / quantityPrecision (-1111 önleme)."""
from __future__ import annotations

import unittest

from binance_futures_trader.client import (
    BinanceFuturesClient,
    _rule_from_symbol_row,
)


class BinancePrecisionTests(unittest.TestCase):
    def _paper_client(self) -> BinanceFuturesClient:
        return BinanceFuturesClient(mode="paper")

    def test_icp_integer_market_qty(self) -> None:
        c = self._paper_client()
        row = {
            "symbol": "ICPUSDT",
            "quantityPrecision": 0,
            "pricePrecision": 6,
            "filters": [
                {
                    "filterType": "LOT_SIZE",
                    "stepSize": "1",
                    "minQty": "1",
                },
                {
                    "filterType": "MARKET_LOT_SIZE",
                    "stepSize": "1",
                    "minQty": "1",
                },
                {"filterType": "PRICE_FILTER", "tickSize": "0.001"},
            ],
        }
        c._symbol_rules["ICPUSDT"] = _rule_from_symbol_row(row)
        self.assertEqual(c.format_qty("ICP", 1523.89, for_market=True), "1523")
        self.assertEqual(c.round_qty("ICP", 1523.89, for_market=True), 1523.0)

    def test_fractional_market_step(self) -> None:
        c = self._paper_client()
        row = {
            "symbol": "BTCUSDT",
            "quantityPrecision": 3,
            "pricePrecision": 2,
            "filters": [
                {
                    "filterType": "LOT_SIZE",
                    "stepSize": "0.001",
                    "minQty": "0.001",
                },
                {
                    "filterType": "MARKET_LOT_SIZE",
                    "stepSize": "0.001",
                    "minQty": "0.001",
                },
            ],
        }
        c._symbol_rules["BTCUSDT"] = _rule_from_symbol_row(row)
        self.assertEqual(c.format_qty("BTC", 0.12349, for_market=True), "0.123")

    def test_unknown_symbol_not_tradable(self) -> None:
        c = self._paper_client()
        c._symbol_rules_warmed = True
        c._symbol_rules["ICPUSDT"] = {"valid": False}
        self.assertFalse(c.symbol_tradable("ICP"))
        with self.assertRaises(ValueError):
            c.round_qty("ICP", 10.0, for_market=True)


if __name__ == "__main__":
    unittest.main()
