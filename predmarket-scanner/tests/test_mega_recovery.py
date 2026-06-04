"""MEGA 9007 — 429/ban recovery ve fresh start."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from elite_trader import mega_live


class MegaRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        mega_live._mega_client = None
        mega_live._mega_outage_since = None
        mega_live._mega_recovery_pending_fresh_start = False
        mega_live._mega_last_recovery_attempt_ts = 0.0
        mega_live._mega_positions = []
        mega_live._mega_closed = []
        mega_live._mega_closed_loaded = True

    def test_mark_outage_only_9007(self) -> None:
        env = {"MEGA_INSTANCE_ID": "9006", "MEGA_LIVE_ORDERS": "1"}
        with patch.dict(os.environ, env, clear=False):
            mega_live.mark_mega_api_outage(reason="429")
            self.assertIsNone(mega_live._mega_outage_since)

    def test_mark_outage_sets_fresh_start_flag(self) -> None:
        env = {
            "MEGA_INSTANCE_ID": "9007",
            "MEGA_LIVE_ORDERS": "1",
            "MEGA_9007_BINANCE_API_KEY": "k" * 40,
            "MEGA_9007_BINANCE_API_SECRET": "s" * 40,
            "MEGA_FRESH_START_ON_RECOVERY": "1",
        }
        with patch.dict(os.environ, env, clear=False):
            mega_live.mark_mega_api_outage(reason="429")
            self.assertIsNotNone(mega_live._mega_outage_since)
            self.assertTrue(mega_live._mega_recovery_pending_fresh_start)

    def test_fresh_start_archives_and_clears(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            data = root / "data" / "mega_9007"
            data.mkdir(parents=True)
            (data / "mega_live_closed.json").write_text(
                json.dumps({"closed": [{"id": 1, "symbol": "BTCUSDT"}]}),
                encoding="utf-8",
            )
            (data / "mega_live_session.json").write_text(
                json.dumps({"wallet_anchor": 5000}),
                encoding="utf-8",
            )
            env = {
                "MEGA_INSTANCE_ID": "9007",
                "MEGA_LIVE_ORDERS": "1",
                "MEGA_9007_BINANCE_API_KEY": "k" * 40,
                "MEGA_9007_BINANCE_API_SECRET": "s" * 40,
            }
            mock_mc = MagicMock()
            mock_mc.paper = False
            mock_mc.exchange_wallet.return_value = {"total_wallet_balance": 5011.0}

            with patch.dict(os.environ, env, clear=False):
                with patch.object(mega_live, "_ROOT", root):
                    with patch.object(mega_live, "get_mega_client", return_value=mock_mc):
                        with patch.object(
                            mega_live,
                            "_fetch_wallet",
                            return_value={"total_wallet_balance": 5011.0},
                        ):
                            out = mega_live.fresh_start_mega_9007_after_recovery(
                                reason="test_recovery"
                            )
            self.assertTrue(out["ok"])
            self.assertAlmostEqual(out["wallet_anchor"], 5011.0)
            self.assertFalse((data / "mega_live_closed.json").exists())
            archives = list((root / "data" / "deleted_archives").glob("mega_9007_*"))
            self.assertEqual(len(archives), 1)
            self.assertTrue((archives[0] / "mega_live_session.json").is_file())

    def test_try_recover_skips_during_ban(self) -> None:
        env = {
            "MEGA_INSTANCE_ID": "9007",
            "MEGA_LIVE_ORDERS": "1",
            "MEGA_9007_BINANCE_API_KEY": "k" * 40,
            "MEGA_9007_BINANCE_API_SECRET": "s" * 40,
        }
        with patch.dict(os.environ, env, clear=False):
            with patch(
                "elite_trader.connection_alerts.ip_ban_active", return_value=True
            ):
                out = mega_live.try_recover_mega_client(force=True)
        self.assertFalse(out["ok"])
        self.assertEqual(out["reason"], "ip_ban")

    def test_try_restore_live_on_client(self) -> None:
        from binance_futures_trader.client import BinanceFuturesClient

        mc = BinanceFuturesClient(
            api_key="k" * 40,
            api_secret="s" * 40,
            testnet=True,
            futures_demo=True,
            mode="testnet",
        )
        mc.paper = True
        with patch.object(mc, "_auth_ok", return_value=(True, None)):
            ok, err = mc.try_restore_live()
        self.assertTrue(ok)
        self.assertIsNone(err)
        self.assertFalse(mc.paper)


if __name__ == "__main__":
    unittest.main()
