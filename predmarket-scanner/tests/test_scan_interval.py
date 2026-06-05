"""Motor vs UI tick scan interval mantığı."""
from __future__ import annotations

import os
import unittest
from unittest.mock import patch


class TestMotorScanInterval(unittest.TestCase):
    def test_env_cap_profile_faster_wins_within_budget(self) -> None:
        os.environ["ELITE_SCAN_INTERVAL_SEC"] = "15"
        os.environ["MOTOR_SCAN_BUDGET_MS"] = "400"
        with patch("binance_elite_pro.execution_profile", return_value={"scan_interval_sec": 0.8}):
            from binance_elite_pro import _effective_motor_scan_interval_sec

            self.assertEqual(_effective_motor_scan_interval_sec(), 0.8)

    def test_env_lower_than_profile_respects_budget_floor(self) -> None:
        os.environ["ELITE_SCAN_INTERVAL_SEC"] = "0.5"
        os.environ["MOTOR_SCAN_BUDGET_MS"] = "850"
        with patch("binance_elite_pro.execution_profile", return_value={"scan_interval_sec": 1.0}):
            from binance_elite_pro import _effective_motor_scan_interval_sec

            self.assertGreaterEqual(_effective_motor_scan_interval_sec(), 1.0)

    def test_ui_tick_default(self) -> None:
        os.environ.pop("ELITE_UI_TICK_INTERVAL_SEC", None)
        from binance_elite_pro import _ui_tick_interval_sec

        self.assertEqual(_ui_tick_interval_sec(), 0.35)


if __name__ == "__main__":
    unittest.main()
