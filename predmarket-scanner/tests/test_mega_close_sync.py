"""MEGA close-sync motor health and session path."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from elite_trader import mega_close_sync as cs


class MegaCloseSyncHealthTests(unittest.TestCase):
    def test_health_includes_error_fields(self) -> None:
        h = cs.close_sync_health()
        self.assertIn("last_error", h)
        self.assertIn("last_error_ts", h)
        self.assertIn("session_path", h)
        self.assertIn("last_reconcile_error", h)

    def test_session_path_helper(self) -> None:
        with patch.dict("os.environ", {"MEGA_INSTANCE_ID": "9007"}, clear=False):
            p = cs._session_path_str()
            self.assertIsNotNone(p)
            self.assertIn("mega_9007", p or "")

    def test_sync_uses_session_path_when_force(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            session = Path(td) / "mega_live_session.json"
            session.write_text(
                json.dumps({"set_at": "2026-01-01T00:00:00+00:00", "wallet_anchor": 5000}),
                encoding="utf-8",
            )
            with patch("elite_trader.mega_live._mega_session_path", return_value=session):
                with patch("elite_trader.mega_live.mega_closed_backfill_suppressed", return_value=True):
                    n = cs.sync_missing_closes_from_exchange(force=True)
            self.assertEqual(n, 0)


if __name__ == "__main__":
    unittest.main()
