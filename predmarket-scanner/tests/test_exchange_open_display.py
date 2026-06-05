"""Binance-exact open position display — positionRisk ham string + ROE."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from elite_trader.exchange_open_display import build_open_positions_for_ui
from elite_trader.exchange_position_sync import apply_exchange_snapshot


def _sample_ep(**overrides) -> dict:
    base = {
        "coin": "BTC",
        "symbol": "BTCUSDT",
        "side": "LONG",
        "contracts": 0.01,
        "entry_price": 65000.5,
        "mark_price": 65100.25,
        "unrealized_pnl": 0.9975,
        "leverage": 5,
        "notional_usd": 651.0025,
        "margin_used": 130.2005,
        "break_even_price": 65026.0,
        "margin_type": "isolated",
        "exchange_update_ms": 1710000000000,
        "exchange_raw": {
            "entryPrice": "65000.50",
            "markPrice": "65100.25000000",
            "unRealizedProfit": "0.99750000",
            "notional": "651.00250000",
            "positionAmt": "0.010",
            "breakEvenPrice": "65026.00000000",
            "isolatedMargin": "130.20050000",
            "positionInitialMargin": "130.20050000",
            "marginType": "isolated",
            "updateTime": "1710000000000",
            "leverage": "5",
        },
    }
    base.update(overrides)
    return base


class TestExchangeOpenDisplay(unittest.TestCase):
    def test_exchange_display_preserves_raw_strings(self) -> None:
        ep = _sample_ep()
        rows = build_open_positions_for_ui([], [ep], MagicMock(paper=True))
        self.assertEqual(len(rows), 1)
        row = rows[0]
        disp = row["exchange_display"]
        self.assertEqual(disp["unRealizedProfit"], "0.99750000")
        self.assertEqual(disp["markPrice"], "65100.25000000")
        self.assertEqual(disp["entryPrice"], "65000.50")
        self.assertEqual(row["data_source"], "binance")
        self.assertEqual(row["unrealized_pnl"], 0.9975)

    def test_roe_uses_margin_not_stake(self) -> None:
        ep = _sample_ep(margin_used=100.0, exchange_raw={
            **_sample_ep()["exchange_raw"],
            "isolatedMargin": "100.00000000",
            "positionInitialMargin": "100.00000000",
        })
        pos: dict = {"side": "LONG"}
        apply_exchange_snapshot(pos, ep)
        expected_roe = 0.9975 / 100.0 * 100
        self.assertAlmostEqual(pos["pnl_pct"], expected_roe, places=6)
        stake_roe = 0.9975 / (651.0025 / 5) * 100
        self.assertNotAlmostEqual(pos["pnl_pct"], stake_roe, places=2)

    def test_apply_exchange_does_not_recompute_unrealized_on_mark_change(self) -> None:
        ep = _sample_ep()
        pos: dict = {"side": "LONG"}
        apply_exchange_snapshot(pos, ep)
        ep2 = _sample_ep(
            mark_price=66000.0,
            unrealized_pnl=10.0,
            exchange_raw={
                **_sample_ep()["exchange_raw"],
                "markPrice": "66000.00000000",
                "unRealizedProfit": "10.00000000",
            },
        )
        apply_exchange_snapshot(pos, ep2)
        self.assertEqual(pos["unrealized_pnl"], 10.0)
        self.assertEqual(pos["exchange_display"]["unRealizedProfit"], "10.00000000")

    def test_no_estimated_entry_fee_without_meta(self) -> None:
        ep = _sample_ep()
        rows = build_open_positions_for_ui([], [ep], MagicMock(paper=True))
        self.assertIsNone(rows[0].get("entry_fee"))

    def test_local_meta_merged(self) -> None:
        ep = _sample_ep()
        local = [
            {
                "symbol": "BTCUSDT",
                "side": "LONG",
                "on_exchange": True,
                "id": 42,
                "signal_source": "Evrim",
                "entry_fee": 0.26,
            }
        ]
        rows = build_open_positions_for_ui(local, [ep], MagicMock(paper=True))
        self.assertEqual(rows[0]["id"], 42)
        self.assertEqual(rows[0]["signal_source"], "Evrim")
        self.assertEqual(rows[0]["entry_fee"], 0.26)


if __name__ == "__main__":
    unittest.main()
