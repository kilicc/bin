"""Tests for MEGA control state machine."""
from __future__ import annotations

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("MEGA_INSTANCE_ID", "9007")
os.environ.setdefault("MEGA_SIM_ENABLED", "1")
os.environ.setdefault("MEGA_LIVE_ORDERS", "0")


class MegaControlTests(unittest.TestCase):
    def setUp(self):
        import elite_trader.mega_control as mc

        mc._state = "RUNNING"
        mc._pausing_since = None

    def test_pause_start_flow(self):
        from elite_trader.mega_control import (
            allow_new_entries,
            control_state,
            request_pause,
            request_start,
        )

        self.assertTrue(allow_new_entries())
        request_pause()
        self.assertEqual(control_state(), "PAUSED")
        self.assertFalse(allow_new_entries())
        with patch("elite_trader.mega_live._mega_positions", []):
            from elite_trader.mega_control import apply_pause_exits

            apply_pause_exits({})
        from elite_trader import mega_control as mc

        self.assertEqual(mc.control_state(), "PAUSED")
        request_start()
        self.assertEqual(control_state(), "RUNNING")

    def test_status_buttons(self):
        from elite_trader.mega_control import get_status, request_pause

        st = get_status()
        self.assertTrue(st["buttons"]["pause"])
        request_pause()
        st = get_status()
        self.assertFalse(st["buttons"]["pause"])


if __name__ == "__main__":
    unittest.main()
