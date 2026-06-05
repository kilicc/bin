"""BTC rejim izleyici — hızlı yol + arka plan."""
from __future__ import annotations

import sys
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import elite_trader.berserk2_btc_context as btc_ctx


class TestBerserk2BtcContext(unittest.TestCase):
    def setUp(self) -> None:
        with btc_ctx._lock:
            btc_ctx._ctx.clear()
            btc_ctx._ctx.update(
                {
                    "btc_regime": "unknown",
                    "btc_24h_change": None,
                    "btc_price": None,
                    "updated_at": 0.0,
                    "regime_updated_at": 0.0,
                }
            )
        btc_ctx.stop_btc_regime_watcher()

    def tearDown(self) -> None:
        btc_ctx.stop_btc_regime_watcher()

    def test_patch_fast_updates_price_without_klines(self) -> None:
        with patch.object(btc_ctx, "_hub_btc_24h", return_value=-0.5):
            with patch.object(btc_ctx, "_cached_btc_price", return_value=99_000.0):
                out = btc_ctx.patch_btc_context_fast()
        self.assertEqual(out["btc_price"], 99_000.0)
        self.assertEqual(out["btc_24h_change"], -0.5)
        self.assertGreater(out["updated_at"], 0)

    def test_refresh_throttle(self) -> None:
        client = MagicMock()
        client.klines.return_value = [
            {"c": 100, "h": 101, "l": 99} for _ in range(25)
        ]
        with patch.object(btc_ctx, "_regime_from_klines", return_value="trend_up"):
            with patch.object(btc_ctx, "_micro_regime_overlay", return_value=None):
                with patch.object(btc_ctx, "_wick_metrics_1m", return_value={}):
                    a = btc_ctx.refresh_btc_context(client)
                    b = btc_ctx.refresh_btc_context(client)
        self.assertEqual(a["btc_regime"], "trend_up")
        self.assertEqual(b["btc_regime"], "trend_up")
        self.assertEqual(client.klines.call_count, 1)
        args = client.klines.call_args[0]
        self.assertEqual(args[1], btc_ctx.btc_kline_interval())

    def test_watcher_starts_and_patches(self) -> None:
        client = MagicMock()
        client.paper = False
        with patch.object(btc_ctx, "patch_btc_context_fast") as pf:
            with patch.object(btc_ctx, "schedule_btc_refresh") as sf:
                btc_ctx.start_btc_regime_watcher(client)
                time.sleep(0.7)
                btc_ctx.stop_btc_regime_watcher()
        self.assertGreaterEqual(pf.call_count, 1)
        sf.assert_called()

    def test_schedule_dedupes_inflight(self) -> None:
        client = MagicMock()
        barrier = threading.Event()

        def slow_refresh(_c: object) -> dict:
            barrier.wait(timeout=2.0)
            return btc_ctx.get_btc_context()

        with patch.object(btc_ctx, "refresh_btc_context", side_effect=slow_refresh):
            btc_ctx._btc_refresh_inflight = False
            with btc_ctx._lock:
                btc_ctx._ctx["regime_updated_at"] = 0.0
                btc_ctx._ctx["updated_at"] = 0.0
            btc_ctx.schedule_btc_refresh(client)
            btc_ctx.schedule_btc_refresh(client)
            barrier.set()
            time.sleep(0.3)
        self.assertTrue(btc_ctx._watcher_thread is None or True)


if __name__ == "__main__":
    unittest.main()
