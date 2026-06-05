"""BTC makro feed — dominance, F&G, veto."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from elite_trader import btc_macro_feed as macro


class TestBtcMacroFeed(unittest.TestCase):
    def setUp(self) -> None:
        with macro._lock:
            macro._macro.clear()
            macro._macro["updated_at"] = 0.0

    def test_macro_entry_blocks_greed_long(self) -> None:
        with macro._lock:
            macro._macro.update({"fng_score": 82, "news_agg_sentiment": "neutral"})
        ok, tag = macro.macro_entry_allowed("LONG", {})
        self.assertFalse(ok)
        self.assertEqual(tag, "macro_fng_extreme_greed")

    def test_cascade_exempt_from_macro(self) -> None:
        with macro._lock:
            macro._macro.update({"fng_score": 90})
        ok, _ = macro.macro_entry_allowed(
            "LONG", {"mega_btc_cascade_direct": True}
        )
        self.assertTrue(ok)

    @patch.object(macro, "_fetch_json")
    def test_fetch_cmc_global(self, fj: MagicMock) -> None:
        fj.return_value = {
            "data": {
                "btc_dominance": 58.2,
                "eth_dominance": 12.1,
                "quote": {"USD": {"total_market_cap": 1e12, "total_volume_24h": 5e10}},
            }
        }
        with patch.dict("os.environ", {"COINMARKETCAP_API_KEY": "test-key"}):
            out = macro._fetch_cmc_global()
        self.assertEqual(out["btc_dominance"], 58.2)

    def test_binance_derivatives_mock(self) -> None:
        client = MagicMock()
        client.paper = False
        client.funding_rate.return_value = 0.0001
        client._get.side_effect = lambda path, params=None: {
            "/fapi/v1/premiumIndex": {"markPrice": "67000", "indexPrice": "66990"},
            "/fapi/v1/ticker/24hr": {"priceChangePercent": "-2.5", "quoteVolume": "1e9"},
            "/fapi/v1/openInterest": {"openInterest": "100"},
        }.get(path, {})
        out = macro._fetch_binance_derivatives(client)
        self.assertIn("funding_rate_pct", out)
        self.assertEqual(out["change_24h_pct"], -2.5)


if __name__ == "__main__":
    unittest.main()
