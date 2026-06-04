"""Tests for lab counterfactual simulator."""
from __future__ import annotations

import unittest

from elite_trader.lab_simulator import simulate_signal


class LabSimulatorTests(unittest.TestCase):
    def test_simulate_presets(self):
        out = simulate_signal({"symbol": "BTCUSDT", "type": "LONG"}, 50000.0)
        self.assertTrue(out["ok"])
        self.assertEqual(len(out["presets"]), 4)
        row = out["presets"][0]
        self.assertIn("tp_net_usd", row)
        self.assertIn("sl_net_usd", row)

    def test_requires_price(self):
        out = simulate_signal({"symbol": "ETHUSDT"}, 0)
        self.assertFalse(out["ok"])


if __name__ == "__main__":
    unittest.main()
