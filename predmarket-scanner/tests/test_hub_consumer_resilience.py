"""Hub tüketici — disk/stale yedek, kopuk banner önleme."""
from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from elite_trader import binance_data_hub as hub


class HubConsumerResilienceTests(unittest.TestCase):
    def setUp(self) -> None:
        hub._stop.set()
        hub._last_good_marks.clear()
        hub._last_good_marks_ts = 0.0
        hub._consumer_cache.clear()
        hub._consumer_cache_ts = 0.0
        hub._hub_fail_streak = 0

    def test_relaxed_marks_from_file_without_connected(self) -> None:
        snap = {
            "ok": True,
            "ts_ms": int(time.time() * 1000),
            "mainnet": {
                "connected": False,
                "lag_ms": 8000,
                "marks": {f"C{i}": float(100 + i) for i in range(20)},
            },
        }
        marks, meta = hub._extract_marks_from_snap(snap, relaxed=True)
        self.assertGreaterEqual(len(marks), 3)

    def test_consumer_marks_from_disk_file(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            hub_dir = root / "data" / "hub"
            hub_dir.mkdir(parents=True)
            feed = {
                "ok": True,
                "ts_ms": int(time.time() * 1000),
                "mainnet": {
                    "connected": True,
                    "lag_ms": 50,
                    "marks": {f"C{i}": float(100 + i) for i in range(25)},
                },
            }
            (hub_dir / "binance_market_feed.json").write_text(
                json.dumps(feed), encoding="utf-8"
            )
            env = {"BINANCE_ELITE_PORT": "9006", "MEGA_INSTANCE_ID": "9006"}
            with patch.dict(os.environ, env, clear=True):
                with patch.object(hub, "_ROOT", root):
                    with patch.object(hub, "_HUB_DIR", hub_dir):
                        with patch.object(hub, "_HUB_FEED_PATH", hub_dir / "binance_market_feed.json"):
                            with patch.object(hub, "_HUB_FEED_TMP", hub_dir / "binance_market_feed.json.tmp"):
                                with patch.object(hub, "_fetch_http_feed", return_value=None):
                                    marks = hub.consumer_marks_bulk(allow_stale=True)
            self.assertGreaterEqual(len(marks), 20)


if __name__ == "__main__":
    unittest.main()
