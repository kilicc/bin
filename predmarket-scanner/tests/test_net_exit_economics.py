"""Net kâr — çıkış/giriş fee+vergi kapıları."""
from __future__ import annotations

import sys
import unittest
import unittest.mock
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from elite_trader.fee_economics import (
    allow_position_close,
    estimate_close_pnl,
    filter_profitable_exit_reason,
    min_gross_for_final_net,
    settled_exit_record_reason,
    tp_sl_gross_triggers,
)
from elite_trader.panel_strategy import evaluate_position_exit


class TestNetExitEconomics(unittest.TestCase):
    def test_spike_peak_blocked_when_net_negative(self):
        """Brüt +$0.12 ama ücret+vergi sonrası net- → SPIKE-PEAK iptal."""
        stake = 216.0
        lev = 3
        gross = 0.12
        reason = filter_profitable_exit_reason(
            "SPIKE-PEAK",
            gross_unreal=gross,
            stake_usd=stake,
            leverage=lev,
            mode_id="berserk2",
        )
        self.assertIsNone(reason)
        est = estimate_close_pnl(gross, stake, lev)
        self.assertLess(est["final_pnl"], 0.08)

    def test_tp_fires_only_when_net_positive(self):
        from elite_trader.fee_economics import tp_sl_gross_triggers

        stake = 216.0
        lev = 3
        tp_thr, _, _, _ = tp_sl_gross_triggers(stake, lev, "berserk2")
        at = evaluate_position_exit(
            opened_at="2026-05-24T12:00:00+00:00",
            unrealized_usd=tp_thr + 0.05,
            tp_target_usd=0.77,
            sl_target_usd=0.43,
            stake_usd=stake,
            leverage=lev,
            mode_id="berserk2",
        )
        self.assertEqual(at, "TP")
        est = __import__(
            "elite_trader.fee_economics", fromlist=["estimate_close_pnl"]
        ).estimate_close_pnl(tp_thr + 0.05, stake, lev)
        self.assertGreaterEqual(est["final_pnl"], 0.08)

    def test_stale_dip_blocked_on_loss(self):
        reason = filter_profitable_exit_reason(
            "STALE-DIP",
            gross_unreal=-0.40,
            stake_usd=216.0,
            leverage=3,
            mode_id="berserk2",
        )
        self.assertIsNone(reason)

    def test_settled_tp_relabeled_net_loss(self):
        settled = {
            "wallet_pnl": -3.03,
            "net_pnl": -3.03,
            "pnl_gross_usd": -2.33,
            "pnl_usd": -2.33,
        }
        self.assertEqual(
            settled_exit_record_reason("TP", settled, mode_id="berserk2"),
            "NET-LOSS",
        )

    def test_settled_tp_kept_when_profitable(self):
        settled = {
            "wallet_pnl": 0.55,
            "net_pnl": 0.55,
            "pnl_gross_usd": 0.90,
            "pnl_usd": 0.90,
        }
        self.assertEqual(
            settled_exit_record_reason("TP", settled, mode_id="berserk2"),
            "TP",
        )

    def test_settled_fee_kill(self):
        settled = {
            "wallet_pnl": -0.30,
            "net_pnl": -0.30,
            "pnl_gross_usd": 0.01,
            "pnl_usd": 0.01,
        }
        self.assertEqual(
            settled_exit_record_reason("TP", settled, mode_id="berserk2"),
            "FEE-KILL",
        )

    def test_tp_on_exchange_falls_back_to_mark_when_book_fill_pessimistic(self):
        """Mark uPnL TP brüt eşiğinde — book fill net düşük olsa da mark tahmini geçerse izin."""
        stake = 700.0
        lev = 10
        tp_g, _, _, _ = tp_sl_gross_triggers(stake, lev, "mega")
        gross = tp_g + 1.0
        pos = {
            "on_exchange": True,
            "symbol": "AVAXUSDT",
            "side": "LONG",
            "stake_usd": stake,
            "leverage": lev,
            "entry_fee": 2.5,
            "unrealized_pnl": gross,
        }

        class _PessimisticClient:
            paper = False

        with unittest.mock.patch(
            "elite_trader.exchange_fill_truth.fill_net_close_ready",
            return_value=(False, 0.5, 2.0, {"source": "book_fill_api", "ok": False}),
        ):
            self.assertTrue(
                allow_position_close(
                    gross_unreal=gross,
                    stake_usd=stake,
                    leverage=lev,
                    exit_reason="TP",
                    mode_id="mega",
                    pos=pos,
                    client=_PessimisticClient(),
                )
            )
        est = estimate_close_pnl(gross, stake, lev, entry_fee=2.5, pos=pos)
        self.assertGreater(est["final_pnl"], 2.0)


if __name__ == "__main__":
    unittest.main()
