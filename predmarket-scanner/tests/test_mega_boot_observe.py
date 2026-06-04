"""MEGA boot observe window."""
from __future__ import annotations

import os
import time
import unittest
from unittest.mock import patch


class MegaBootObserveTests(unittest.TestCase):
    def test_blocks_then_allows(self) -> None:
        import elite_trader.mega_boot_observe as bo

        bo.reset_boot_clock()
        with patch.dict(
            os.environ,
            {"MEGA_BOOT_OBSERVE": "1", "MEGA_BOOT_OBSERVE_SEC": "120"},
            clear=False,
        ):
            import importlib

            importlib.reload(bo)
            self.assertTrue(bo.boot_observe_active())
            self.assertIn("gözlem", bo.boot_entry_block_reason().lower())
            bo._process_boot_at = time.time() - 130
            self.assertFalse(bo.boot_observe_active())
            self.assertEqual(bo.boot_entry_block_reason(), "")

    def test_disabled(self) -> None:
        import elite_trader.mega_boot_observe as bo

        with patch.dict(os.environ, {"MEGA_BOOT_OBSERVE": "0"}, clear=False):
            import importlib

            importlib.reload(bo)
            self.assertFalse(bo.boot_observe_active())


if __name__ == "__main__":
    unittest.main()
