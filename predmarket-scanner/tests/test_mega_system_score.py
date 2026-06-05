"""mega_system_score — P2 gate."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from elite_trader import mega_system_score as sc


class MegaSystemScoreTests(unittest.TestCase):
    def test_gate_off_allows(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "MEGA_SYSTEM_SCORE_GATE": "0",
                "MEGA_SYSTEM_SCORE_MIN": "90",
            },
        ):
            sc._history_cache = None
            ok, reason, score = sc.mega_system_entry_allowed(
                {"symbol": "BTCUSDT", "type": "LONG"}
            )
            self.assertTrue(ok)
            self.assertGreaterEqual(score, 0.0)

    def test_flash_bypass_when_gate_on(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "MEGA_SYSTEM_SCORE_GATE": "1",
                "MEGA_SYSTEM_SCORE_MIN": "99",
                "MEGA_SYSTEM_SCORE_FLASH_BYPASS": "1",
            },
        ):
            sc._history_cache = {"trade_count": 0, "flash_loss_rate_pct": 80}
            ok, _, _ = sc.mega_system_entry_allowed(
                {"symbol": "DOGEUSDT", "type": "SHORT", "mega_flash_reversal": True}
            )
            self.assertTrue(ok)

    def test_compute_score_range(self) -> None:
        with patch.object(
            sc,
            "build_system_context",
            create=True,
        ):
            with patch(
                "elite_trader.mega_system_context.build_system_context",
                return_value={
                    "btc": {"regime": "chop", "context_age_sec": 5},
                    "market_regime": {},
                    "system": {"hub": {"mark_lag_ms": 200}},
                },
            ):
                score, _ = sc.compute_live_score({"symbol": "ETHUSDT", "type": "LONG"})
                self.assertGreaterEqual(score, 50.0)
                self.assertLessEqual(score, 100.0)


if __name__ == "__main__":
    unittest.main()
