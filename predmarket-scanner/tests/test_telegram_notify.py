"""Telegram mesaj formatı — birim testleri (ağ yok)."""
from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from elite_trader import telegram_notify as tg


class TelegramFormatTests(unittest.TestCase):
    def test_reason_human_tier(self) -> None:
        self.assertIn("Kademeli", tg._reason_human("TIER-10"))
        self.assertIn("Flash", tg._reason_human("SPIKE-FLASH"))

    def test_duration_human(self) -> None:
        self.assertEqual("45 sn", tg._duration_human(45))
        self.assertIn("dk", tg._duration_human(125))

    def test_notify_opened_structure(self) -> None:
        with patch.object(tg, "telegram_enabled", return_value=True), patch.object(
            tg, "enqueue_message"
        ) as mock_q:
            tg.notify_position_opened(
                {
                    "symbol": "ETHUSDT",
                    "side": "LONG",
                    "entry_price": 3421.5,
                    "stake_usd": 5000,
                    "leverage": 20,
                    "tp_target_usd": 120,
                    "tp_net_target_usd": 45,
                    "signal_source": "mega_flash_reversal",
                    "on_exchange": True,
                    "id": 17,
                    "order_id": "abc123",
                }
            )
        text = mock_q.call_args[0][0]
        self.assertIn("Yeni pozisyon", text)
        self.assertIn("ETH", text)
        self.assertIn("Flash reversal", text)
        self.assertIn("Canlı", text)
        self.assertNotIn("ETHUSDT", text)

    def test_open_positions_digest_includes_system_context(self) -> None:
        rows = [
            {
                "symbol": "ETHUSDT",
                "side": "LONG",
                "unrealized_pnl": 12.5,
                "max_unreal_seen": 20.0,
                "stake_usd": 1000,
                "leverage": 10,
                "id": 1,
                "entry_time_str": "2026-06-01 10:00:00",
            }
        ]
        fake_btc = {
            "regime_label": "BTC ↓ trend",
            "ready": True,
            "ready_label": "Hazır",
            "btc_24h_change": -1.2,
            "btc_price": 95000.0,
            "context_age_sec": 12.0,
            "bearish": True,
            "bear_tag": "btc_bear",
            "btc_cascade": {"phase_label": "dump", "active": True},
            "btc_macro": {"tag": "risk-off"},
            "btc_liq": {"label": "short squeeze risk"},
        }
        with patch(
            "elite_trader.mega_direction_guard.btc_context_snapshot",
            return_value=fake_btc,
        ), patch(
            "elite_trader.mega_market_regime.snapshot",
            return_value={"regime": "quiet", "regime_locked": True, "reject_mix": {"btc_stale": 0.4}},
        ), patch(
            "elite_trader.mega_system_context.build_system_context",
            return_value={
                "system": {
                    "hub": {"alive": True, "mark_lag_ms": 120},
                    "reject_top": [{"reason": "btc_regime_unknown", "share": 0.25}],
                }
            },
        ), patch(
            "elite_trader.mega_control.get_status",
            return_value={"state": "RUNNING", "motor_active": True},
        ), patch.object(tg, "_closed_counts_tr_today", return_value=(2, 5.0, 10, 8.0)):
            text = tg.format_open_positions_digest(rows)
        self.assertIn("Toplam uPnL", text)
        self.assertIn("BTC", text)
        self.assertIn("BTC ↓ trend", text)
        self.assertIn("Piyasa", text)
        self.assertIn("quiet", text)
        self.assertIn("Hub", text)
        self.assertIn("ETH", text)

    def test_notify_closed_structure(self) -> None:
        tg._close_notify_seen.clear()
        with patch.object(tg, "telegram_enabled", return_value=True), patch.object(
            tg, "enqueue_message"
        ) as mock_q, patch.object(tg, "_chat_id", return_value="-111"), patch.object(
            tg, "_closes_chat_ids", return_value=["-222"]
        ), patch.object(tg, "_should_telegram_notify_close", return_value=True), patch.object(
            tg, "_load_close_notify_persisted"
        ), patch.object(tg, "_persist_close_notify_key"):
            tg.notify_position_closed(
                {
                    "symbol": "DOGEUSDT",
                    "side": "LONG",
                    "exit_reason": "SPIKE-FLASH",
                    "entry_price": 0.12,
                    "exit_price": 0.125,
                    "pnl_gross_usd": 12.4,
                    "wallet_pnl": 6.05,
                    "total_fees": 4.2,
                    "funding_fee": 0.01,
                    "stake_usd": 3000,
                    "leverage": 15,
                    "duration_sec": 320,
                    "max_unreal_seen": 18.0,
                    "id": 17,
                    "on_exchange": True,
                    "close_initiator": "bot",
                    "exit_time_str": "2026-06-01 12:00:00",
                },
                exit_reason="SPIKE-FLASH",
            )
        self.assertEqual(mock_q.call_count, 2)
        main_text = mock_q.call_args_list[0][0][0]
        detail_text = mock_q.call_args_list[1][0][0]
        self.assertEqual(mock_q.call_args_list[0][1].get("chat_id"), "-111")
        self.assertEqual(mock_q.call_args_list[1][1].get("chat_id"), "-222")
        self.assertIn("Pozisyon kapandı", main_text)
        self.assertIn("Kapanış logu", detail_text)
        self.assertIn("Flash spike", main_text)
        self.assertIn("SPIKE-FLASH", detail_text)
        self.assertIn("5 dk", detail_text)
        self.assertIn("+$6.05", main_text)

    def test_closes_chat_ids_from_env(self) -> None:
        with patch.dict(
            os.environ,
            {"MEGA_TELEGRAM_CLOSES_CHAT_ID": "-5257722394,-999"},
            clear=False,
        ):
            self.assertEqual(tg._closes_chat_ids(), ["-5257722394", "-999"])

    def test_digest_empty(self) -> None:
        out = tg.format_open_positions_digest([])
        self.assertIn("Açık pozisyon yok", out)

    def test_digest_shows_realized_net(self) -> None:
        with patch.object(tg, "_closed_counts_tr_today", return_value=(3, 42.5, 3, 42.5)):
            out = tg.format_open_positions_digest(
                [
                    {
                        "symbol": "BTCUSDT",
                        "side": "LONG",
                        "unrealized_pnl": 10.0,
                        "max_unreal_seen": 15.0,
                        "stake_usd": 100,
                        "leverage": 10,
                        "entry_time_str": "2026-06-01 10:00:00",
                    }
                ]
            )
        self.assertIn("bugün net", out)
        self.assertIn("+$42.50", out)
        self.assertIn("3 kapanış", out)

    def test_tr_time_footer_and_open(self) -> None:
        out = tg.format_open_positions_digest(
            [
                {
                    "symbol": "ETHUSDT",
                    "side": "LONG",
                    "unrealized_pnl": 12.5,
                    "max_unreal_seen": 20.0,
                    "stake_usd": 500,
                    "leverage": 10,
                    "entry_time_str": "2026-06-01 10:00:00",
                }
            ]
        )
        self.assertIn("açılış", out)
        self.assertIn("TR", out)
        self.assertNotIn("UTC", out)
        self.assertIn("01.06.2026 13:00", out)

    def test_now_footer_converts_exit_to_tr(self) -> None:
        foot = tg._now_footer("2026-06-01 12:00:00")
        self.assertIn("TR", foot)
        self.assertIn("15:00", foot)

    def test_pnl_summary(self) -> None:
        closed = [{"wallet_pnl": 10.0}, {"wallet_pnl": -3.0}]
        with patch.object(
            tg, "_all_closed_rows", return_value=closed
        ), patch.object(
            tg, "_closed_rows_recent", return_value=closed
        ), patch.object(tg, "_open_positions_snapshot", return_value=[]):
            out = tg.format_pnl_summary()
        self.assertIn("Performans özeti", out)
        self.assertIn("+$7.00", out)
        self.assertIn("gerçekleşen", out)
        self.assertIn("50%", out)


if __name__ == "__main__":
    os.environ.setdefault("MEGA_INSTANCE_ID", "9006")
    unittest.main()
