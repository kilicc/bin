"""mega_system_context — P0 snapshot."""
from __future__ import annotations

import unittest
from unittest.mock import patch

import elite_trader.mega_system_context as ctx


class MegaSystemContextTests(unittest.TestCase):
    def test_build_disabled(self) -> None:
        with patch.dict("os.environ", {"MEGA_SYSTEM_CONTEXT_ENABLED": "0"}):
            self.assertEqual(ctx.build_system_context("entry", pos={"symbol": "BTCUSDT"}), {})

    def test_attach_entry_exit(self) -> None:
        with patch.dict("os.environ", {"MEGA_SYSTEM_CONTEXT_ENABLED": "1"}):
            pos = {"id": 1, "symbol": "DOGEUSDT", "side": "SHORT", "stake_usd": 1000}
            ctx.attach_entry_context(
                pos, signal={"symbol": "DOGEUSDT", "type": "SHORT", "change": 0.05}
            )
            self.assertEqual(
                pos.get("entry_context", {}).get("schema"), "mega_system_context_v1"
            )
            self.assertEqual(pos["entry_context"]["phase"], "entry")
            closed = {"symbol": "DOGEUSDT", "wallet_pnl": -10.0}
            ctx.attach_exit_context(
                closed,
                pos=pos,
                exit_reason="SPIKE-FLASH",
                settlement={"wallet_pnl": -10.0},
            )
            self.assertEqual(closed.get("exit_context", {}).get("phase"), "exit")
            self.assertEqual(closed.get("entry_context"), pos.get("entry_context"))


if __name__ == "__main__":
    unittest.main()
