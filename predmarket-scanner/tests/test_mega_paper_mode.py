"""MEGA paper mod — SL yok, stake, kaldıraç, paralel canlı."""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from elite_trader import parallel_universe_engine as pue
from elite_trader.mode_engines.mega_scoring import evaluate_mega_entry, mega_leverage
from elite_trader.mode_profiles import get_profile
from elite_trader.mode_registry import enabled_mode_ids, resolve_mode_id
from elite_trader.panel_strategy import evaluate_position_exit, live_only_execution


def _configure_pue() -> None:
    pue.configure(
        edge_fn=lambda ch: abs(ch) * 0.01,
        formula_fn=lambda ch: min(1.0, abs(ch) * 0.02),
        kelly_fn=lambda ch, side: 600.0,
        min_edge=0.01,
        min_formula=0.01,
        session_start=5000.0,
        stake_bounds_fn=lambda: (100.0, 125.0),
        max_open_fn=lambda: 4,
        wr_fn=lambda: 0.5,
        leverage_fn=lambda s, d: 3,
        tradable_symbols={"BTCUSDT", "ETHUSDT", "SOLUSDT"},
        scan_universe={"BTCUSDT", "ETHUSDT", "SOLUSDT"},
    )


class TestMegaPaperMode(unittest.TestCase):
    def test_mega_registered(self):
        self.assertEqual(resolve_mode_id("mega"), "mega")
        prof = get_profile("mega")
        self.assertTrue(prof.get("exit_tp_only"))
        self.assertTrue(prof.get("no_loss_close"))
        self.assertFalse(prof.get("stale_enabled"))

    def test_mega_leverage_tiers(self):
        prof = get_profile("mega")
        lev_env = {
            "MEGA_LEVERAGE_MIN": "5",
            "MEGA_LEVERAGE_WEAK": "5",
            "MEGA_LEVERAGE_MEDIUM": "8",
            "MEGA_LEVERAGE_STRONG": "10",
        }
        with patch.dict(os.environ, lev_env, clear=False):
            sig = {"mega_meta": {"mega_score": 75}, "strength": "Strong"}
            self.assertEqual(mega_leverage(sig, "Strong", prof), 10)
            sig2 = {"mega_meta": {"mega_score": 60}, "strength": "Medium"}
            self.assertEqual(mega_leverage(sig2, "Medium", prof), 8)
            sig3 = {"mega_meta": {"mega_score": 40}, "strength": "Weak"}
            self.assertEqual(mega_leverage(sig3, "Weak", prof), 5)
            sig4 = {"mega_meta": {"mega_score": 40}, "strength": "Weak"}
            with patch.dict(os.environ, {**lev_env, "MEGA_LEVERAGE_WEAK": "2"}, clear=False):
                self.assertEqual(mega_leverage(sig4, "Weak", prof), 5)

    def test_exit_tp_only_blocks_sl(self):
        prof = get_profile("mega")
        stake = 500.0
        lev = 5
        tp_usd = stake * float(prof["tp_stake_pct"])
        sl_usd = stake * float(prof.get("sl_stake_pct") or 0.01) or 50.0
        reason = evaluate_position_exit(
            opened_at="2020-01-01T00:00:00Z",
            unrealized_usd=-sl_usd * 2,
            tp_target_usd=tp_usd,
            sl_target_usd=sl_usd,
            stake_usd=stake,
            leverage=lev,
            mode_id="mega",
        )
        self.assertIsNone(reason)

    def test_exit_tp_on_profit(self):
        prof = get_profile("mega")
        stake = 500.0
        lev = 3
        tp_usd = stake * float(prof["tp_stake_pct"])
        reason = evaluate_position_exit(
            opened_at="2020-01-01T00:00:00Z",
            unrealized_usd=tp_usd + 5,
            tp_target_usd=tp_usd,
            sl_target_usd=50,
            stake_usd=stake,
            leverage=lev,
            mode_id="mega",
        )
        self.assertEqual(reason, "TP")

    def test_paper_parallel_side_by_side(self):
        env = {
            "ELITE_LIVE_ONLY": "1",
            "ELITE_PAPER_PARALLEL": "1",
            "BINANCE_LIVE_ORDERS": "1",
            "ELITE_ENABLED_MODES": "berserk2,mega",
        }
        with patch.dict(os.environ, env, clear=False):
            self.assertFalse(live_only_execution())
            self.assertIn("mega", enabled_mode_ids())

    def test_mega_entry_rejects_small_move(self):
        prof = get_profile("mega")
        signal = {
            "symbol": "SOLUSDT",
            "type": "LONG",
            "change": 0.015,
            "strength": "Medium",
            "edge": 0.1,
            "formula_score": 0.6,
        }
        ctx = {"profile": prof, "spread_pct": 0.04, "vol_ratio": 1.2}
        with patch("elite_trader.mega_volatility.enabled", return_value=False):
            with patch("elite_trader.berserk2_movers.is_top_mover", return_value=False):
                ok, reason, _ = evaluate_mega_entry(signal, ctx, prof, edge=0.1, formula=0.6)
        self.assertFalse(ok)
        self.assertEqual(reason, "mega_move_too_small")

    def test_mega_relative_hot_tier_accepts_quiet_move(self):
        prof = get_profile("mega")
        env = {
            "MEGA_RELATIVE_ENTRY": "1",
            "MEGA_VOL_REL_MIN_MOVE_PCT": "0.005",
            "MEGA_MIN_MOVE_PCT": "0.018",
            "MEGA_MIN_SCORE": "28",
            "MEGA_REQUIRE_TOP_MOVER": "0",
        }
        fake_row = {
            "symbol": "SOLUSDT",
            "change_pct": 0.011,
            "rank": 2,
            "tier": "hot",
            "vol_score": 18.0,
        }
        with patch.dict(os.environ, env, clear=False):
            with patch(
                "elite_trader.mega_volatility.enabled",
                return_value=True,
            ):
                with patch(
                    "elite_trader.mega_volatility.thresholds",
                    return_value={
                        "min_move": 0.018,
                        "min_score": 28.0,
                        "min_edge": 0.02,
                        "require_top_mover": False,
                        "tier": "hot",
                        "rank": 2,
                        "regime": "seek+transition(score_pressure)",
                    },
                ):
                    with patch(
                        "elite_trader.mega_volatility.row_for",
                        return_value=fake_row,
                    ):
                        signal = {
                            "symbol": "SOLUSDT",
                            "type": "LONG",
                            "change": 0.011,
                            "strength": "Medium",
                            "price": 140.0,
                        }
                        ctx = {
                            "profile": prof,
                            "spread_pct": 0.03,
                            "vol_ratio": 1.15,
                            "vol_score": 18.0,
                        }
                        ok, reason, meta = evaluate_mega_entry(
                            signal, ctx, prof, edge=0.08, formula=0.55
                        )
        self.assertTrue(ok, msg=f"expected pass got {reason} meta={meta}")
        self.assertLessEqual(meta.get("min_move_pct", 99), 0.011)

    def test_open_shadow_respects_mega_stake_cap(self):
        _configure_pue()
        prof = get_profile("mega")
        st = pue._load()
        book = st["universes"].setdefault("mega", pue._empty_book())
        book["open"] = []
        pue._save(st)
        signal = {
            "symbol": "ETHUSDT",
            "type": "LONG",
            "change": 0.35,
            "strength": "Strong",
            "edge": 0.12,
            "formula_score": 0.7,
            "mega_meta": {
                "mega_score": 80,
                "combined_stake_mult": 1.0,
                "leverage": 10,
            },
        }
        with patch.object(pue, "_entry_allowed", return_value=(True, "")):
            with patch(
                "elite_trader.parallel_universe_engine.is_live_binance_motor",
                lambda mid: False,
            ):
                pue.on_market_signal_for_mode("mega", signal, 2500.0)
        st2 = pue._load()
        opens = st2["universes"]["mega"]["open"]
        if opens:
            stake = float(opens[-1]["stake_usd"])
            self.assertGreaterEqual(stake, 500.0)
            self.assertLessEqual(stake, 1500.0)
            self.assertIn(int(opens[-1].get("leverage") or 0), (2, 3, 5, 7, 10))


    def test_berserk2_paper_equity_floor(self) -> None:
        env = {
            "BERSERK2_PAPER_ONLY": "1",
            "BERSERK2_PAPER_EQUITY_USD": "25000",
            "BERSERK2_PAPER_FIXED_STAKE_USD": "3000",
            "STARTING_BALANCE": "5000",
        }
        with patch.dict(os.environ, env, clear=False):
            from elite_trader.paper_book import (
                berserk2_paper_fallback_stake,
                effective_paper_equity,
                paper_book_equity_floor,
            )

            self.assertEqual(paper_book_equity_floor("berserk2"), 25000.0)
            self.assertEqual(effective_paper_equity(0.0, "berserk2"), 25000.0)
            fb = berserk2_paper_fallback_stake(
                min_stake=500.0, max_stake=3000.0, open_count=0, max_open=5
            )
            self.assertEqual(fb, 3000.0)

    def test_paper_sim_skips_live_margin_gate(self) -> None:
        env = {
            "MEGA_SIM_ENABLED": "1",
            "MEGA_LIVE_ORDERS": "0",
            "MEGA_SIM_EQUITY_USD": "10000",
        }
        with patch.dict(os.environ, env, clear=False):
            from elite_trader import mega_live as ml

            ml._mega_wallet.clear()
            with patch.object(ml, "_fetch_wallet", return_value={}):
                ok, reason = ml._mega_open_margin_ok(1000.0)
                self.assertTrue(ok)
                self.assertEqual(reason, "")
                self.assertTrue(ml.mega_paper_sim_only())


if __name__ == "__main__":
    unittest.main()
