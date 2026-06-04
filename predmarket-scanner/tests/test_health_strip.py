"""Health strip API aggregation."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from elite_trader.health_strip import health_strip_payload


class HealthStripTests(unittest.TestCase):
    def test_payload_shape(self) -> None:
        with patch("elite_trader.mega_control.get_status", return_value={"state": "RUNNING"}):
            with patch(
                "elite_trader.mega_close_sync.close_sync_health",
                return_value={"alive": True, "last_error": None},
            ):
                with patch("elite_trader.training_lab.lab_api.executor_metrics", return_value={"inflight": 0}):
                    with patch("elite_trader.health_strip._llm_ping_cached", return_value={"ok": True}):
                        p = health_strip_payload()
        self.assertTrue(p.get("ok"))
        self.assertIn("control", p)
        self.assertIn("close_sync", p)
        self.assertIn("lab", p)
        self.assertIn("llm", p)


if __name__ == "__main__":
    unittest.main()
