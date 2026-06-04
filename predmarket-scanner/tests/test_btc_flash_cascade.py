"""BTC şelale — 1m, beta sıra, kitap/hacim."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from elite_trader import btc_flash_cascade as casc


def _btc_hist(prices: list[float]) -> dict[str, list]:
    return {
        "BTCUSDT": [{"price": p, "time": float(i)} for i, p in enumerate(prices)]
    }


def _klines_drop() -> list[dict]:
    kl = []
    for i in range(20):
        h, l, c = 100.0, 99.5, 99.8
        if i >= 15:
            h, l, c = 100.0, 97.5, 98.0
        if i == 18:
            h, l, c = 100.0, 97.0, 97.2
        kl.append({"h": h, "l": l, "c": c, "v": 100.0 if i < 18 else 250.0})
    kl.append({"h": 97.5, "l": 97.0, "c": 97.1, "v": 80.0})
    return kl


class TestBtcFlashCascade(unittest.TestCase):
    def test_cascade_from_1m_klines(self) -> None:
        with patch(
            "elite_trader.berserk2_btc_context.get_btc_klines_cached",
            _klines_drop,
        ):
            with patch.object(casc, "_attach_context_metrics", lambda s: s):
                st = casc.detect_btc_cascade(
                    _btc_hist([100.0, 99.0, 97.1]), price=97.1
                )
        self.assertIsNotNone(st)
        self.assertEqual(st.get("source"), "1m_klines")
        self.assertIn(st.get("phase"), ("cascade_down", "capitulation", "recovery"))

    def test_sort_beta_eth_before_apt(self) -> None:
        syms = ["APTUSDT", "ETHUSDT", "DOGEUSDT", "SOLUSDT"]
        out = casc.sort_cascade_symbols(syms, {"phase": "cascade_down"})
        self.assertEqual(out[0], "ETHUSDT")
        self.assertLess(out.index("ETHUSDT"), out.index("APTUSDT"))

    def test_direct_btc_short_needs_vol(self) -> None:
        st = {"phase": "cascade_down", "btc_drop_pct": 0.5, "btc_vol_spike": False}
        with patch.object(casc, "cascade_volume_confirmed", return_value=False):
            sig = casc.build_cascade_direct_btc_short(97000.0, st)
        self.assertIsNone(sig)

    def test_recovery_blocks_late_short(self) -> None:
        prices = [100.0] * 4 + [99.0, 98.0, 97.5, 98.5, 99.0]
        late, tag = casc.cascade_blocks_late_short(_btc_hist(prices))
        self.assertTrue(late)
        self.assertIn("late_short", tag)

    def test_bounce_favors_long_cap(self) -> None:
        st = {
            "phase": "capitulation",
            "btc_recovery_frac": 0.06,
            "momentum_up": True,
        }
        with patch.object(casc, "enabled", return_value=True):
            with patch.object(casc, "detect_btc_cascade", return_value=st):
                ok, out = casc.bounce_favors_long(_btc_hist([100.0, 98.0, 99.0]))
        self.assertTrue(ok)
        self.assertEqual(out.get("phase"), "capitulation")


if __name__ == "__main__":
    unittest.main()
