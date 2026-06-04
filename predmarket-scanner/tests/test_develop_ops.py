"""Develop + ops monitor tests."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from elite_trader.training_lab import develop_api, lab_store, ops_monitor


class DevelopApiTests(unittest.TestCase):
    def test_scenario_summary(self) -> None:
        r = develop_api.scenario_summary()
        self.assertTrue(r.get("ok"))
        self.assertIn("keys", r)

    def test_develop_status(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            docs = root / "documents"
            docs.mkdir()
            (docs / ".knowledge_bootstrap_ts").write_text("ts\n", encoding="utf-8")
            with patch.object(lab_store, "lab_data_dir", return_value=root):
                st = develop_api.develop_status()
            self.assertTrue(st.get("ok"))
            self.assertTrue(st["knowledge"]["bootstrapped"])


class OpsMonitorTests(unittest.TestCase):
    def test_knowledge_status(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with patch.object(lab_store, "lab_data_dir", return_value=root):
                k = ops_monitor.knowledge_status()
            self.assertIn("lessons_count", k)


if __name__ == "__main__":
    unittest.main()
