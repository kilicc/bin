"""mega_system_context_backfill — retro snapshot."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from elite_trader.mega_system_context_backfill import (
    build_retro_context,
    enrich_closed_row,
    load_audit_index,
    merge_closed_unique,
)


class MegaSystemContextBackfillTests(unittest.TestCase):
    def test_build_retro_has_backfill_flag(self) -> None:
        row = {
            "id": 9,
            "symbol": "DOGEUSDT",
            "side": "SHORT",
            "exit_reason": "SPIKE-FLASH",
            "wallet_pnl": -10.0,
            "pre_send_net": 36.0,
            "opened_at_iso": "2026-05-31T22:59:00+00:00",
            "exit_time_iso": "2026-05-31T23:01:00+00:00",
        }
        ctx = build_retro_context("exit", row)
        self.assertTrue(ctx.get("backfill"))
        self.assertIsNone(ctx.get("btc"))
        self.assertEqual(ctx["exec"]["wallet_pnl"], -10.0)

    def test_merge_dedupe_by_oid(self) -> None:
        a = [{"id": 1, "exchange_close_order_id": "99", "symbol": "BTCUSDT", "side": "LONG"}]
        b = [{"id": 2, "exchange_close_order_id": "99", "symbol": "BTCUSDT", "side": "LONG", "wallet_pnl": 1}]
        m = merge_closed_unique([a, b])
        self.assertEqual(len(m), 1)
        self.assertEqual(m[0].get("wallet_pnl"), 1)

    def test_audit_index_and_enrich(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            ap = Path(td) / "audit.jsonl"
            ap.write_text(
                json.dumps(
                    {
                        "event": "close_pre_send_ok",
                        "position_id": 3,
                        "pre_send_net": 12.5,
                        "pre_send_gross": 18.0,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            idx = load_audit_index(ap)
            row = {"id": 3, "symbol": "ETHUSDT", "side": "LONG"}
            self.assertTrue(enrich_closed_row(row, idx))
            self.assertTrue(row["entry_context"]["backfill"])
            self.assertEqual(row["exit_context"]["position"]["pre_send_net"], 12.5)


if __name__ == "__main__":
    unittest.main()
