"""mega_system_report — P1 analytics."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from elite_trader.mega_system_report import analyze_closed, format_telegram


class MegaSystemReportTests(unittest.TestCase):
    def test_analyze_empty(self) -> None:
        self.assertEqual(analyze_closed([])["trade_count"], 0)

    def test_analyze_win_loss(self) -> None:
        rows = [
            {"wallet_pnl": 10.0, "exit_reason": "TP"},
            {"wallet_pnl": -5.0, "exit_reason": "SPIKE-FLASH", "pre_send_net": 20.0},
        ]
        s = analyze_closed(rows)
        self.assertEqual(s["trade_count"], 2)
        self.assertEqual(s["wins"], 1)
        self.assertEqual(s["flash_trades"], 1)

    def test_format_telegram(self) -> None:
        text = format_telegram(
            {
                "window_hours": 24,
                "window_tr": "2026-06-01",
                "window": {"trade_count": 3, "win_rate_pct": 66.0, "net_usd": 1.5},
                "all_time": {"trade_count": 10, "win_rate_pct": 50.0, "net_usd": 0},
                "live": {"btc_regime": "chop"},
            }
        )
        self.assertIn("MEGA sistem kartı", text)


if __name__ == "__main__":
    unittest.main()
