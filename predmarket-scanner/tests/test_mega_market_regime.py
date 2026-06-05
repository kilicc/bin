"""MEGA piyasa rejimi — slot dolana kadar kilitleme."""
from __future__ import annotations

import os
import time
import unittest
from unittest.mock import patch

from elite_trader import mega_market_regime as mr


class MegaRegimeLockTests(unittest.TestCase):
    def setUp(self) -> None:
        self._orig_state = dict(mr._state)

    def tearDown(self) -> None:
        mr._state.clear()
        mr._state.update(self._orig_state)

    def test_record_open_preserves_transition_until_full(self) -> None:
        env = {"MEGA_REGIME_LOCK_UNTIL_FULL": "1", "MEGA_IDLE_TRANSITION": "1"}
        with patch.dict(os.environ, env, clear=False):
            mr._state["transition_active"] = True
            mr._state["transition_reason"] = "idle_blend"
            mr._state["last_open_at"] = 0.0
            mr.record_open(symbol="BTCUSDT", side="LONG", open_count=2, max_open=4)
            self.assertTrue(mr._state.get("transition_active"))
            self.assertEqual(float(mr._state.get("last_open_at") or 0), 0.0)

    def test_record_open_resets_transition_when_slots_full(self) -> None:
        env = {"MEGA_REGIME_LOCK_UNTIL_FULL": "1"}
        with patch.dict(os.environ, env, clear=False):
            mr._state["transition_active"] = True
            mr.record_open(symbol="BTCUSDT", side="LONG", open_count=4, max_open=4)
            self.assertFalse(mr._state.get("transition_active"))

    def test_regime_locks_on_first_open(self) -> None:
        env = {"MEGA_REGIME_LOCK_UNTIL_FULL": "1"}
        with patch.dict(os.environ, env, clear=False):
            mr._state["regime"] = "quiet"
            mr._state["regime_locked"] = False
            mr._sync_regime_lock(open_count=1)
            self.assertTrue(mr._state.get("regime_locked"))
            self.assertEqual(mr._state.get("locked_regime"), "quiet")

    def test_record_sample_skips_regime_switch_when_locked(self) -> None:
        env = {"MEGA_REGIME_LOCK_UNTIL_FULL": "1", "MEGA_REGIME_AUTO": "1"}
        with patch.dict(os.environ, env, clear=False):
            mr._state["regime"] = "normal"
            mr._state["regime_locked"] = True
            mr._state["locked_regime"] = "normal"
            mr._state["samples"] = []
            rows = [{"tier": "hot", "change_pct": 0.12}] * 5
            with patch.object(mr, "_regime_locked", return_value=True):
                out = mr.record_sample(rows)
            self.assertEqual(out, "normal")
            self.assertEqual(mr._state.get("regime"), "normal")

    def test_live_transition_updates_while_locked(self) -> None:
        env = {
            "MEGA_REGIME_LOCK_UNTIL_FULL": "1",
            "MEGA_REGIME_LOCK_LIVE_TRANSITION": "1",
            "MEGA_IDLE_TRANSITION": "1",
            "MEGA_IDLE_OPEN_SEC": "60",
        }
        with patch.dict(os.environ, env, clear=False):
            mr._state["regime_locked"] = True
            mr._state["locked_regime"] = "quiet"
            mr._state["locked_transition"] = True
            mr._state["locked_transition_reason"] = "edge_pressure"
            mr._state["last_open_at"] = time.time() - 5
            mix = {"mega_move_too_small": 0.55, "mega_edge_low": 0.10}
            with patch.object(mr, "_slot_counts", return_value=(2, 4)):
                trans = mr._transition_status(mix)
            self.assertTrue(trans.get("active"))
            self.assertTrue(trans.get("live"))
            self.assertEqual(trans.get("reason"), "move_pressure")


if __name__ == "__main__":
    unittest.main()
