"""Flash pump → SHORT reversal."""
from __future__ import annotations

import unittest

from elite_trader.berserk2_flash_reversal import (
    build_flash_pump_reversal_candidate,
    detect_flash_pump_reversal,
)


def _hist(prices: list[float]) -> list[dict]:
    return [{"price": p, "time": "12:00:00"} for p in prices]


class FlashPumpReversalTests(unittest.TestCase):
    def test_detect_pump_fade_short(self) -> None:
        # Pompa < %1.2 (BERSERK2_FLASH_PUMP_MAX_PCT) — aksi halde sinyal elenir
        prices = (
            [100.0, 99.92, 99.88, 99.85, 99.82]
            + [99.86, 99.92, 99.98, 100.05, 100.12, 100.18]
            + [100.14, 100.08, 100.02]
        )
        ph = {"ETHUSDT": _hist(prices)}
        det = detect_flash_pump_reversal("ETHUSDT", 100.02, ph, {})
        self.assertIsNotNone(det)
        self.assertTrue(det.get("flash_pump_reversal"))

    def test_build_candidate_is_short(self) -> None:
        prices = (
            [50.0, 49.96, 49.94, 49.92]
            + [49.95, 49.98, 50.02, 50.06, 50.10, 50.14]
            + [50.12, 50.10, 50.08]
        )
        ph = {"SOLUSDT": _hist(prices)}
        cand = build_flash_pump_reversal_candidate("SOLUSDT", 50.08, ph, {})
        self.assertIsNotNone(cand)
        self.assertEqual(cand.get("type"), "SHORT")
        self.assertIn("FlashReversal-SHORT", str(cand.get("signal_source")))


if __name__ == "__main__":
    unittest.main()
