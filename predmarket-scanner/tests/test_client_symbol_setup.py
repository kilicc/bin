"""Binance symbol setup — -4047/-4067 spam önleme."""
from __future__ import annotations

import os
import unittest
from unittest.mock import patch

import httpx

from binance_futures_trader import client as bcl


class ClientSymbolSetupTests(unittest.TestCase):
    def setUp(self) -> None:
        bcl._symbol_setup_cooldown.clear()
        bcl._symbol_setup_logged.clear()
        bcl._global_setup_block_until = 0.0

    def test_benign_error_skips_connection_alert(self) -> None:
        from elite_trader import connection_alerts as ca

        ca._last_error = None
        ca.note_binance_error('{"code":-4067,"msg":"Position side cannot be changed"}')
        self.assertIsNone(ca._last_error)

    def test_unknown_order_skips_connection_alert(self) -> None:
        from elite_trader import connection_alerts as ca

        ca._last_error = None
        ca.note_binance_error('{"code":-2011,"msg":"Unknown order sent."}')
        self.assertIsNone(ca._last_error)

    def test_margin_block_sets_cache(self) -> None:
        c = bcl.BinanceFuturesClient(
            api_key="k",
            api_secret="s",
            mode="testnet",
            testnet=True,
            futures_demo=True,
        )
        c.paper = False
        c._margin_set.clear()

        def _boom(*_a, **_k):
            req = httpx.Request("POST", "https://demo-fapi.binance.com/fapi/v1/marginType")
            resp = httpx.Response(
                400,
                request=req,
                text='{"code":-4067,"msg":"Position side cannot be changed if there exists open orders."}',
            )
            raise httpx.HTTPStatusError("400", request=req, response=resp)

        with patch.object(c, "_post", side_effect=_boom):
            mt = c.ensure_margin_type("BTC")
        self.assertEqual(mt, "ISOLATED")
        self.assertEqual(c._margin_set.get("BTC"), "ISOLATED")
        self.assertTrue(c._symbol_setup_blocked("BTC"))

    def test_mega_margin_gate(self) -> None:
        env = {"MEGA_OPEN_MARGIN_BUFFER_USD": "20"}
        with patch.dict(os.environ, env, clear=False):
            from elite_trader import mega_live as ml

            ml._mega_wallet = {"available_balance": 100.0, "_ts": 1e9}
            with patch.object(ml, "_fetch_wallet", return_value=ml._mega_wallet):
                ok, reason = ml._mega_open_margin_ok(150.0)
                self.assertFalse(ok)
                self.assertIn("available=", reason)
                ok2, _ = ml._mega_open_margin_ok(70.0)
                self.assertTrue(ok2)


if __name__ == "__main__":
    unittest.main()
