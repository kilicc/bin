"""Binance REST bütçe — -1003 önleme."""
from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

from elite_trader import binance_rest_budget as brb


class BinanceRestBudgetTests(unittest.TestCase):
    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self._path = os.path.join(self._td.name, "budget.json")
        self._env = patch.dict(
            os.environ,
            {
                "ELITE_BINANCE_REST_BUDGET_FILE": self._path,
                "ELITE_BINANCE_REST_MAX_PER_MIN": "60",
            },
            clear=False,
        )
        self._env.start()

    def tearDown(self) -> None:
        self._env.stop()
        self._td.cleanup()

    def test_acquire_respects_cap(self) -> None:
        for _ in range(60):
            self.assertTrue(brb.acquire_rest_slot(weight=1, timeout=1.0))
        self.assertFalse(brb.acquire_rest_slot(weight=1, timeout=0.2))

    def test_near_limit(self) -> None:
        for _ in range(50):
            brb.acquire_rest_slot(weight=1, timeout=1.0)
        self.assertTrue(brb.near_limit(0.8))


if __name__ == "__main__":
    unittest.main()
