"""Checkpoint snapshot parse and rollback preview."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from elite_trader import system_checkpoint_md as scp


class CheckpointRollbackTests(unittest.TestCase):
    def test_parse_snapshot_from_md(self) -> None:
        snap = {"collected_at": "2026-01-01T00:00:00+00:00", "panel_strategy_state": {"x": 1}}
        md = "## FULL_STATE_SNAPSHOT\n\n```json\n" + json.dumps(snap) + "\n```\n"
        with tempfile.TemporaryDirectory() as td:
            cp_dir = Path(td) / "checkpoints"
            cp_dir.mkdir()
            fname = "20260101_test.md"
            (cp_dir / fname).write_text(md, encoding="utf-8")
            with patch.object(scp, "CHECKPOINT_DIR", cp_dir):
                with patch.object(scp, "read_checkpoint_content", return_value=md):
                    parsed = scp.parse_checkpoint_snapshot(fname)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.get("panel_strategy_state"), {"x": 1})

    def test_rollback_preview(self) -> None:
        snap = {"panel_strategy_state": {"mode": "mega"}, "mode_profiles": {"modes": {"mega": {}}}}
        md = "## FULL_STATE_SNAPSHOT\n\n```json\n" + json.dumps(snap) + "\n```\n"
        with patch.object(scp, "read_checkpoint_content", return_value=md):
            with patch.object(scp, "_safe_filename", return_value="test.md"):
                prev = scp.rollback_preview("test.md")
        self.assertTrue(prev.get("ok"))


if __name__ == "__main__":
    unittest.main()
