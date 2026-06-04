"""Pipeline banner — hub kopuk / evren tick eksik."""
from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from elite_trader.pipeline_alerts import build_pipeline_alerts, merge_into_connection_alerts


class PipelineAlertsTests(unittest.TestCase):
    def test_hub_down_critical(self) -> None:
        env = {"BINANCE_ELITE_PORT": "9006", "MEGA_INSTANCE_ID": "9006"}
        live = {
            "mark_ws": {"health": "stale", "coins": 0, "lag_ms": 5000},
            "bookticker": {"ok": False},
            "async_hub": {"data_hub": {"age_ms": 20000}},
        }
        scanner = {"watchlist_total": 68, "symbols_with_ticks": 0}
        with patch.dict(os.environ, env, clear=True):
            with patch(
                "elite_trader.binance_data_hub.hub_consumer_mode", return_value=True
            ):
                alerts = build_pipeline_alerts(live=live, scanner=scanner)
        codes = {a["code"] for a in alerts}
        self.assertIn("hub_feed_down", codes)

    def test_merge_raises_severity(self) -> None:
        base = {"ok": True, "severity": "ok", "alerts": [], "binance": {}}
        live = {
            "mark_ws": {"health": "ok", "coins": 500, "lag_ms": 50},
            "async_hub": {"data_hub": {"age_ms": 100}},
        }
        scanner = {"watchlist_total": 68, "symbols_with_ticks": 68}
        merged = merge_into_connection_alerts(
            base, live=live, scanner=scanner, skip_paper_mode_banner=True
        )
        self.assertTrue(merged.get("ok"))
        self.assertEqual(merged.get("pipeline", {}).get("symbols_with_ticks"), 68)


if __name__ == "__main__":
    unittest.main()
