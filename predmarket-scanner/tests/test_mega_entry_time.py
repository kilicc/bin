"""MEGA — sembol başına açılış zamanı (kilitli kayıt, emir zamanı)."""
from __future__ import annotations

import unittest

from elite_trader.mega_live import (
    _mega_entry_fields_from_ep,
    _mega_entry_fields_from_order,
    mega_position_open_ts,
)


class MegaEntryTimeTests(unittest.TestCase):
    def test_locked_existing_not_overwritten_by_update_ms(self) -> None:
        existing = {
            "entry_time": 1748736000.0,
            "entry_time_str": "2026-06-01 00:00:00",
            "opened_at_iso": "2026-06-01T00:00:00+00:00",
            "entry_time_locked": True,
        }
        ep = {"exchange_update_ms": 1780358400140}
        ts, s, iso = _mega_entry_fields_from_ep(ep, existing)
        self.assertAlmostEqual(ts, 1748736000.0, delta=1.0)
        self.assertIn("2026-06-01", s)
        open_ts = mega_position_open_ts({**existing, **{"entry_time": ts}})
        self.assertIsNotNone(open_ts)
        self.assertAlmostEqual(open_ts or 0, 1748736000.0, delta=2.0)

    def test_entry_fields_from_order_transact_time(self) -> None:
        order = {"transactTime": 1780364989438}
        times = _mega_entry_fields_from_order(order)
        self.assertIsNotNone(times)
        ts, s, iso = times  # type: ignore[misc]
        self.assertGreater(ts, 0)
        self.assertIn("2026", s)
        self.assertIn("T", iso)


if __name__ == "__main__":
    unittest.main()
