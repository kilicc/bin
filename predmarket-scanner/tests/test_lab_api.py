"""Lab lessons and executor metrics."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from elite_trader.training_lab import lab_api, lab_store


class LabApiTests(unittest.TestCase):
    def test_add_lesson(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with patch.object(lab_store, "lab_data_dir", return_value=root):
                (root / "lessons.jsonl").touch()
                r = lab_api.add_lesson("test lesson", session_id="s1")
            self.assertTrue(r.get("ok"))

    def test_executor_metrics(self) -> None:
        m = lab_api.executor_metrics()
        self.assertIn("inflight", m)
        self.assertIn("last_latency_ms", m)

    def test_read_lessons_empty(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            with patch.object(lab_store, "lab_data_dir", return_value=Path(td)):
                self.assertEqual(lab_store.list_lessons(), [])


if __name__ == "__main__":
    unittest.main()
