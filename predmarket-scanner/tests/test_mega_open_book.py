"""MEGA 9006 — açık/kapalı pozisyon defteri diske yazılır ve restart sonrası yüklenir."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from elite_trader import mega_live as ml


class MegaOpenBookTests(unittest.TestCase):
    def setUp(self) -> None:
        ml._mega_positions = []
        ml._mega_closed = []
        ml._mega_position_id = 1
        ml._mega_closed_loaded = False
        ml._mega_open_book_loaded = False
        ml._mega_persist_open_book_ts = 0.0
        ml._mega_client = None

    def test_open_book_persist_reload_and_close_record(self) -> None:
        env = {
            "MEGA_INSTANCE_ID": "9006",
            "MEGA_LIVE_ORDERS": "0",
            "MEGA_SIM_ENABLED": "1",
            "MEGA_SIM_EQUITY_USD": "10000",
        }
        plan = {
            "symbol": "BTCUSDT",
            "side": "LONG",
            "leverage": 5,
            "size": 0.01,
            "entry_price": 50000.0,
            "stake_usd": 500.0,
            "tp_target": 0.02,
            "sl_target": 0.01,
            "tp_target_usd": 10.0,
            "sl_target_usd": 5.0,
            "tp_net_target_usd": 8.0,
            "round_trip_fee_est_usd": 1.0,
            "strength": "Medium",
            "mega_elite_entry": False,
        }
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            data = root / "data" / "mega_9006"
            data.mkdir(parents=True)
            from elite_trader import parallel_universe_engine as pe

            with patch.dict(os.environ, env, clear=True):
                with patch.object(ml, "_ROOT", root):
                    with patch.object(ml, "_plan_open", return_value=plan):
                        with patch.object(
                            pe, "entry_gate_for_mode", return_value=(True, "")
                        ), patch.object(pe, "record_live_open"), patch.object(
                            pe, "record_live_close"
                        ), patch.object(
                            ml, "get_mega_client", return_value=None
                        ):
                            self.assertTrue(
                                ml._try_open_sim_from_signal(
                                    {"symbol": "BTCUSDT", "type": "LONG"},
                                    50000.0,
                                    skip_gate=True,
                                )
                            )
                            self.assertEqual(len(ml._mega_positions), 1)
                            open_path = data / "mega_live_open.json"
                            self.assertTrue(open_path.is_file())
                            payload = json.loads(open_path.read_text(encoding="utf-8"))
                            self.assertEqual(len(payload.get("open") or []), 1)
                            self.assertEqual(payload["open"][0]["symbol"], "BTCUSDT")

                            pos = ml._mega_positions[0]
                            ml._close_mega_sim_position(pos, 0, "TP")
                            self.assertEqual(len(ml._mega_positions), 0)
                            payload2 = json.loads(open_path.read_text(encoding="utf-8"))
                            self.assertEqual(payload2.get("open"), [])
                            self.assertEqual(len(ml._mega_closed), 1)
                            self.assertTrue(ml._mega_closed[0].get("sim"))

                            ml._mega_positions = []
                            ml._mega_closed = []
                            ml._mega_closed_loaded = False
                            ml._mega_open_book_loaded = False
                            ml._ensure_mega_closed_loaded()
                            self.assertEqual(len(ml._mega_positions), 0)
                            self.assertEqual(len(ml._mega_closed), 1)


if __name__ == "__main__":
    unittest.main()
