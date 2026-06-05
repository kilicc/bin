"""ELITE_PAPER_PARALLEL — canlı berserk2 + paper mega yan yana."""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from elite_trader import parallel_universe_engine as pue
from elite_trader.panel_strategy import is_live_binance_motor, live_only_execution


class TestPaperParallelSideBySide(unittest.TestCase):
    def test_live_only_false_when_paper_parallel(self):
        env = {
            "ELITE_LIVE_ONLY": "1",
            "ELITE_PAPER_PARALLEL": "1",
            "BINANCE_LIVE_ORDERS": "1",
            "ELITE_ENABLED_MODES": "berserk2,mega",
            "ELITE_DEFAULT_EXECUTION_MODE": "berserk2",
        }
        with patch.dict(os.environ, env, clear=False):
            self.assertFalse(live_only_execution())

    def test_mega_not_live_motor_when_berserk2_exec(self):
        env = {
            "ELITE_DEFAULT_EXECUTION_MODE": "berserk2",
            "BINANCE_LIVE_ORDERS": "1",
            "BERSERK2_PAPER_ONLY": "0",
        }
        with patch.dict(os.environ, env, clear=False):
            with patch(
                "elite_trader.panel_strategy.active_execution_mode",
                return_value="berserk2",
            ):
                self.assertTrue(is_live_binance_motor("berserk2"))
                self.assertFalse(is_live_binance_motor("mega"))

    def test_paper_mode_ids_includes_mega(self):
        env = {
            "ELITE_ENABLED_MODES": "berserk2,mega",
            "ELITE_DEFAULT_EXECUTION_MODE": "berserk2",
            "BINANCE_LIVE_ORDERS": "1",
        }
        with patch.dict(os.environ, env, clear=False):
            with patch(
                "elite_trader.panel_strategy.is_live_binance_motor",
                lambda mid: mid == "berserk2",
            ):
                ids = pue.paper_mode_ids()
        self.assertIn("mega", ids)
        self.assertNotIn("berserk2", ids)


if __name__ == "__main__":
    unittest.main()
