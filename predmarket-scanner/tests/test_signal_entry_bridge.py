"""Tick/motor giriş köprüsü — kısa momentum aday üretimi."""
from __future__ import annotations

import os
import unittest
from datetime import datetime

from elite_trader.signal_paths import build_raw_momentum_candidate_flex


class TestSignalEntryBridge(unittest.TestCase):
    def test_short_window_candidate(self) -> None:
        os.environ["UI_APPROACHING_LOOKBACK"] = "3"
        os.environ["ENTRY_SHORT_MOMENTUM_PCT"] = "0.02"
        sym = "TESTUSDT"
        base = 100.0
        hist = [
            {"time": datetime.utcnow().isoformat(), "price": base}
            for _ in range(4)
        ]
        hist[-1] = {"time": datetime.utcnow().isoformat(), "price": base * 1.0005}
        ph = {sym: hist}
        cand = build_raw_momentum_candidate_flex(sym, base * 1.0005, ph)
        self.assertIsNotNone(cand)
        self.assertEqual(cand["symbol"], sym)
        self.assertGreater(abs(float(cand["change"])), 0.02)


if __name__ == "__main__":
    unittest.main()
