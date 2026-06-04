"""Income API — Transaction History net kapanış."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from elite_trader.income_close import (
    aggregate_close_income_at_ms,
    apply_income_wallet_to_close_row,
    income_matches_realized,
)


class IncomeCloseTests(unittest.TestCase):
    def test_xrp_close_net_matches_transaction_history(self) -> None:
        """Realized 18.55 + iki commission satırı → net ~10.54."""
        rows = [
            {"type": "COMMISSION", "income": -4.00696199, "time": 1_709_000_000_000},
            {"type": "REALIZED_PNL", "income": 18.55075, "time": 1_709_000_000_000},
            {"type": "COMMISSION", "income": -3.99953624, "time": 1_709_000_002_000},
        ]
        client = MagicMock()
        client.paper = False
        client.income_history.return_value = rows

        out = aggregate_close_income_at_ms(
            client, "XRP", 1_709_000_000_000, since_ms=1_708_000_000_000
        )
        self.assertIsNotNone(out)
        assert out is not None
        self.assertAlmostEqual(out["realized_pnl"], 18.55075, places=4)
        self.assertAlmostEqual(out["total_commission"], 8.00649823, places=4)
        self.assertAlmostEqual(out["wallet_pnl"], 10.54425177, places=3)
        self.assertEqual(out["commission_lines"], 2)

    def test_apply_income_to_close_row(self) -> None:
        income = {
            "realized_pnl": 18.55075,
            "wallet_pnl": 10.5443,
            "total_commission": 8.0065,
            "commission_lines": 2,
            "exit_ms": 1,
        }
        row = apply_income_wallet_to_close_row(
            {"pnl_usd": 14.5, "net_pnl": 14.5, "stake_usd": 1000},
            income,
        )
        self.assertAlmostEqual(row["pnl_usd"], 18.5508, places=3)
        self.assertAlmostEqual(row["net_pnl"], 10.5443, places=3)
        self.assertAlmostEqual(row["total_fees"], 8.0065, places=3)

    def test_income_matches_realized(self) -> None:
        self.assertTrue(
            income_matches_realized({"realized_pnl": 18.55}, 18.55075)
        )
        self.assertFalse(income_matches_realized({"realized_pnl": 1.0}, 18.55))


if __name__ == "__main__":
    unittest.main()
