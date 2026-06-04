"""MEGA canlı emir — ayrı API anahtarı yönlendirmesi."""
from __future__ import annotations

import os
import time
import unittest
from unittest.mock import patch

from elite_trader.futures_order_router import route_order_intent
from elite_trader.order_gate import route_order


class MegaLiveRoutingTests(unittest.TestCase):
    def test_mega_secondary_live_route(self) -> None:
        env = {
            "MEGA_LIVE_ORDERS": "1",
            "MEGA_BINANCE_API_KEY": "test_key",
            "MEGA_BINANCE_API_SECRET": "test_secret",
            "BINANCE_LIVE_ORDERS": "1",
        }
        with patch.dict(os.environ, env, clear=False):
            from elite_trader import mega_live

            mega_live._mega_client = None
            intent = {"symbol": "BTCUSDT", "side": "LONG"}
            res = route_order_intent(
                "mega",
                intent,
                active_futures_mode="berserk2",
                live_orders_enabled=True,
            )
            self.assertTrue(res.send_live)
            self.assertEqual(res.reason, "mega_secondary_live")

            gate = route_order(
                "mega",
                intent,
                active_futures_mode="berserk2",
                live_orders_enabled=True,
            )
            self.assertTrue(gate.send_live)

    def test_is_live_binance_motor_mega(self) -> None:
        env = {
            "MEGA_LIVE_ORDERS": "1",
            "MEGA_BINANCE_API_KEY": "k",
            "MEGA_BINANCE_API_SECRET": "s",
        }
        with patch.dict(os.environ, env, clear=False):
            from elite_trader.panel_strategy import is_live_binance_motor

            self.assertTrue(is_live_binance_motor("mega"))
            self.assertFalse(is_live_binance_motor("berserk2"))


class MegaClosedDedupeTests(unittest.TestCase):
    def test_dedupe_by_close_order_id(self) -> None:
        from elite_trader import mega_live

        mega_live._mega_closed = [
            {
                "id": 6,
                "symbol": "APTUSDT",
                "side": "SHORT",
                "exchange_close_order_id": "207276571",
                "stake_usd": 411.0,
                "leverage": 5,
                "net_pnl": -6.96,
                "duration_sec": 171.0,
                "exit_reason": "NET-LOSS",
            },
            {
                "id": 7,
                "symbol": "APTUSDT",
                "side": "SHORT",
                "exchange_close_order_id": "207276571",
                "stake_usd": 1001.0,
                "leverage": 2,
                "net_pnl": -6.96,
                "backfilled": True,
                "sync_source": "exchange_userTrades",
                "exit_reason": "CLOSE",
            },
        ]
        removed = mega_live._dedupe_mega_closed(persist=False)
        self.assertEqual(removed, 1)
        self.assertEqual(len(mega_live._mega_closed), 1)
        kept = mega_live._mega_closed[0]
        self.assertEqual(kept["id"], 6)
        self.assertEqual(kept["leverage"], 5)
        self.assertAlmostEqual(float(kept["net_pnl"]), -6.96)

    def test_dedupe_bot_and_sync_same_trade(self) -> None:
        from elite_trader import mega_live

        mega_live._mega_closed = [
            {
                "id": 71,
                "symbol": "LINKUSDT",
                "side": "LONG",
                "entry_price": 9.168,
                "exit_price": 9.186,
                "net_pnl": 10.46,
                "final_pnl": 10.46,
                "exit_reason": "TP",
                "exit_time": 1717030679.0,
                "exit_time_str": "2026-05-30 00:17:59",
            },
            {
                "id": 72,
                "symbol": "LINKUSDT",
                "side": "LONG",
                "entry_price": 9.168,
                "exit_price": 9.186,
                "net_pnl": 10.46,
                "final_pnl": 10.46,
                "exchange_close_order_id": "574227017",
                "backfilled": True,
                "sync_source": "exchange_userTrades",
                "exit_reason": "TP",
                "exit_time": 1717030675.0,
                "exit_time_str": "2026-05-30 00:17:55",
            },
        ]
        removed = mega_live._dedupe_mega_closed(persist=False)
        self.assertEqual(removed, 1)
        self.assertEqual(len(mega_live._mega_closed), 1)
        kept = mega_live._mega_closed[0]
        self.assertEqual(kept["id"], 71)
        self.assertEqual(kept["exchange_close_order_id"], "574227017")

    def test_dedupe_same_position_id(self) -> None:
        from elite_trader import mega_live

        mega_live._mega_closed = [
            {
                "id": 67,
                "symbol": "SOLUSDT",
                "side": "LONG",
                "net_pnl": 11.45,
                "exit_reason": "TP",
                "exit_time_str": "2026-05-30 01:32:00",
            },
            {
                "id": 67,
                "symbol": "SOLUSDT",
                "side": "LONG",
                "net_pnl": 11.45,
                "exchange_close_order_id": "1924827444",
                "exit_reason": "SPIKE-FLASH",
                "exit_time_str": "2026-05-30 01:32:03",
            },
        ]
        removed = mega_live._dedupe_mega_closed(persist=False)
        self.assertEqual(removed, 1)
        self.assertEqual(len(mega_live._mega_closed), 1)

    def test_keep_separate_same_symbol_different_exits(self) -> None:
        from elite_trader import mega_live

        mega_live._mega_closed = [
            {
                "id": 71,
                "symbol": "LINKUSDT",
                "side": "LONG",
                "net_pnl": 10.46,
                "exit_time_str": "2026-05-30 00:17:59",
            },
            {
                "id": 76,
                "symbol": "LINKUSDT",
                "side": "LONG",
                "net_pnl": 15.59,
                "exit_time_str": "2026-05-30 01:32:17",
            },
        ]
        removed = mega_live._dedupe_mega_closed(persist=False)
        self.assertEqual(removed, 0)
        self.assertEqual(len(mega_live._mega_closed), 2)


class MegaAlgoPruneTests(unittest.TestCase):
    def test_prune_orphan_symbol_orders(self) -> None:
        from elite_trader import mega_live

        mega_live._mega_positions = []
        mega_live._mega_positions_cache = []
        mega_live._mega_algo_prune_ts = 0.0

        class FakeMc:
            paper = False
            canceled_all: list[str] = []

            def open_algo_orders(self, coin=None):
                del coin
                return [
                    {"symbol": "LINKUSDT", "algoId": 101},
                    {"symbol": "SOLUSDT", "algoId": 202},
                ]

            def cancel_all_open_algo_orders(self, coin):
                self.canceled_all.append(coin)
                return {"code": 200}

            def cancel_algo_order(self, coin, aid):
                del coin, aid

        mc = FakeMc()
        with patch.dict(os.environ, {"MEGA_ALGO_AUTO_PRUNE": "1"}, clear=False):
            n = mega_live.prune_mega_algo_orders(mc, force=True)
        self.assertEqual(n, 2)
        self.assertEqual(sorted(mc.canceled_all), ["LINK", "SOL"])


class MegaEliteOverflowTests(unittest.TestCase):
    def test_wallet_full_no_overflow_slots(self) -> None:
        from elite_trader import mega_live
        from elite_trader.mode_engines.mega_scoring import is_mega_elite_signal

        env = {
            "MEGA_WALLET_FULL_BALANCE": "1",
            "MEGA_ELITE_OVERRIDE": "1",
            "MEGA_ELITE_MIN_SCORE": "72",
            "MEGA_ELITE_EXTRA_SLOTS": "2",
        }
        signal = {
            "symbol": "SOLUSDT",
            "type": "LONG",
            "change": 0.05,
            "strength": "Strong",
            "mega_meta": {
                "mega_score": 78.0,
                "vol_tier": "hot",
                "vol_rank": 2,
                "breakout_score": 62.0,
                "spike_meta": {"fake_spike": False},
            },
        }
        with patch.dict(os.environ, env, clear=False):
            self.assertTrue(is_mega_elite_signal(signal))
            mega_live._mega_positions = [{"id": i, "symbol": f"X{i}USDT"} for i in range(4)]
            with patch.object(mega_live, "_mega_deployable_for_new_stake", return_value=5000.0):
                self.assertFalse(mega_live._mega_elite_overflow_entry(signal))
                self.assertEqual(mega_live._mega_open_slot_limit(signal), 5)

    def test_slot_limit_from_deployable_margin(self) -> None:
        from elite_trader import mega_live

        signal = {
            "symbol": "SOLUSDT",
            "type": "LONG",
            "change": 0.03,
            "mega_meta": {"mega_score": 40, "vol_tier": "warm"},
        }
        mega_live._mega_positions = [{"id": i, "stake_usd": 1000} for i in range(4)]
        with patch.dict(os.environ, {"MEGA_WALLET_FULL_BALANCE": "1"}, clear=False):
            with patch.object(mega_live, "_mega_deployable_for_new_stake", return_value=900.0):
                self.assertEqual(mega_live._mega_open_slot_limit(signal), 1)

    def test_flash_uses_same_wallet_cap(self) -> None:
        from elite_trader import mega_live

        signal = {
            "symbol": "XRPUSDT",
            "type": "LONG",
            "mega_flash_reversal": True,
        }
        mega_live._mega_positions = [{"id": i, "symbol": f"Y{i}USDT", "stake_usd": 1000} for i in range(4)]
        with patch.dict(os.environ, {"MEGA_WALLET_FULL_BALANCE": "1"}, clear=False):
            with patch.object(mega_live, "_mega_deployable_for_new_stake", return_value=800.0):
                self.assertFalse(mega_live._mega_flash_overflow_entry(signal))
                self.assertEqual(mega_live._mega_open_slot_limit(signal), 1)


class MegaFlashScanGateTests(unittest.TestCase):
    def test_flash_skips_entry_gate_in_process_scan(self) -> None:
        from elite_trader import mega_live

        sig = {
            "symbol": "XRPUSDT",
            "type": "LONG",
            "mega_flash_reversal": True,
        }
        mega_live._mega_positions = [{"id": i, "symbol": f"Y{i}USDT"} for i in range(4)]
        mega_live._scan_seen.clear()
        with patch.dict(
            os.environ,
            {"MEGA_ELITE_EXTRA_SLOTS": "2", "MEGA_EXTRA_SLOT_MIN_FREE_USD": "500"},
            clear=False,
        ):
            with patch.object(mega_live, "mega_motor_active", return_value=True):
                with patch.object(mega_live, "_mega_available_margin", return_value=800.0):
                    with patch.object(
                        mega_live, "try_open_from_signal", return_value=False
                    ) as mock_open:
                        with patch(
                            "elite_trader.parallel_universe_engine.entry_gate_for_mode",
                            return_value=(False, "would_block"),
                        ):
                            mega_live.process_scan_candidate(sig, 1.25)
        mock_open.assert_called_once()
        args, kwargs = mock_open.call_args
        self.assertTrue(kwargs.get("skip_gate"))


class MegaProfitTierTests(unittest.TestCase):
    def test_tier_lock_upgrades_and_close_on_retrace(self) -> None:
        from elite_trader import mega_live

        pos = {
            "stake_usd": 1000.0,
            "leverage": 10,
            "unrealized_pnl": 12.0,
            "max_unreal_seen": 18.0,
            "max_net_seen": 11.5,
            "entry_fee": 4.0,
        }
        with patch.dict(
            os.environ,
            {
                "MEGA_PROFIT_TIER_LOCK": "1",
                "MEGA_PROFIT_TIER_NET_USD": "5,10,20",
                "MEGA_PROFIT_TIER_LOCK_FRAC": "0.92",
                "MEGA_PROFIT_TIER_RETRACE_FRAC": "0.88",
            },
            clear=False,
        ):
            with patch.object(mega_live, "_mega_touch_peak_net"):
                mega_live._mega_update_profit_tier_lock(pos)
            self.assertEqual(pos.get("mega_locked_net_tier"), 10.0)
            self.assertAlmostEqual(pos["mega_locked_net_floor"], 9.2, places=1)
            with patch.object(
                mega_live, "_mega_estimated_wallet_net", return_value=8.0
            ):
                reason = mega_live._mega_profit_tier_close_reason(
                    pos, stake=1000.0, lev=10, mc=None
                )
            self.assertEqual(reason, "TIER-10")

    def test_fast_close_allowed_for_tier_without_full_tp_gross(self) -> None:
        from elite_trader import mega_live

        pos = {
            "mega_locked_net_floor": 4.6,
            "mega_locked_net_tier": 5,
            "tp_fast_close": True,
            "entry_fee": 4.0,
        }
        with patch.dict(os.environ, {"MEGA_SPIKE_MIN_CLOSE_NET_USD": "2"}, clear=False):
            with patch(
                "elite_trader.fee_economics.min_gross_for_final_net",
                return_value=9.0,
            ):
                ok = mega_live.mega_fast_profit_close_allowed(
                    pos,
                    "TIER-5",
                    10.5,
                    1000.0,
                    10,
                    mode_id="mega",
                )
        self.assertTrue(ok)


class MegaTpStateTests(unittest.TestCase):
    def test_exchange_pos_to_local_preserves_tp_id(self) -> None:
        from elite_trader import mega_live

        existing = {
            "id": 7,
            "stake_usd": 800.0,
            "exchange_tp_order_id": "1000000090062811",
            "exchange_tp_is_algo": True,
            "exchange_tp_arm_failed": False,
        }
        ep = {
            "symbol": "SOLUSDT",
            "side": "LONG",
            "entry_price": 82.0,
            "mark_price": 82.5,
            "contracts": 10.0,
            "leverage": 5,
            "unrealized_pnl": 1.2,
        }
        row = mega_live._exchange_pos_to_local(ep, existing)
        self.assertEqual(row["exchange_tp_order_id"], "1000000090062811")
        self.assertTrue(row["exchange_tp_is_algo"])

    def test_adopt_exchange_tp_binds_algo(self) -> None:
        from elite_trader import mega_live

        pos = {"symbol": "SOLUSDT", "side": "LONG", "id": 1}
        mega_live._mega_tp_adopts_total = 0

        class FakeMc:
            paper = False

            def open_algo_orders(self, coin):
                self.coin = coin
                return [
                    {
                        "symbol": "SOLUSDT",
                        "algoId": 90062811,
                        "triggerPrice": 83.0,
                        "orderType": "TAKE_PROFIT_MARKET",
                    }
                ]

        ok = mega_live._adopt_exchange_tp(pos, FakeMc())
        self.assertTrue(ok)
        self.assertEqual(pos["exchange_tp_order_id"], "90062811")
        self.assertEqual(mega_live._mega_tp_adopts_total, 1)

    def test_maybe_arm_rate_limited(self) -> None:
        from elite_trader import mega_live

        pos = {"symbol": "SOLUSDT", "side": "LONG", "id": 99, "size": 1.0, "entry_price": 80}
        mega_live._mega_tp_arm_attempt_ts = {99: time.time()}
        armed: list[str] = []

        class FakeMc:
            paper = False

            def open_algo_orders(self, coin):
                return []

            def take_profit_market_order(self, *a, **k):
                armed.append("x")
                return {"algoId": 1}

        with patch.dict(os.environ, {"MEGA_TP_ARM_SEC": "120"}, clear=False):
            mega_live._maybe_arm_exchange_tp(pos, FakeMc())
        self.assertEqual(armed, [])


class MegaNetTpLockTests(unittest.TestCase):
    def test_wld_scenario_net_tp_take(self) -> None:
        from elite_trader import mega_live

        pos = {
            "symbol": "WLDUSDT",
            "side": "LONG",
            "tp_net_target_usd": 20.3751,
            "max_unreal_seen": 19.6928916,
            "unrealized_pnl": 19.6928916,
            "entry_fee": 1.4013336,
            "stake_usd": 519.77,
            "leverage": 7,
        }
        env = {
            "MEGA_NET_TP_LOCK": "1",
            "MEGA_NET_TP_LOCK_FRAC": "0.95",
            "MEGA_NET_TP_TAKE_FRAC": "0.92",
        }
        with patch.dict(os.environ, env, clear=False):
            reason = mega_live._mega_net_tp_close_reason(
                pos, stake=519.77, lev=7, mc=None
            )
        self.assertEqual(reason, "TP")

    def test_mega_needs_fast_exit_near_net(self) -> None:
        from elite_trader import mega_live

        mega_live._mega_positions = [
            {
                "symbol": "WLDUSDT",
                "tp_net_target_usd": 20.0,
                "max_unreal_seen": 18.0,
                "unrealized_pnl": 17.0,
            }
        ]
        with patch.dict(os.environ, {"MEGA_FAST_EXIT_WATCH_FRAC": "0.88"}, clear=False):
            self.assertTrue(mega_live.mega_needs_fast_exit())

    def test_mega_needs_fast_exit_mark_spike_zone(self) -> None:
        from elite_trader import mega_live
        from elite_trader.fee_economics import fast_scalp_min_gross_usd

        stake, lev = 510.0, 5
        flash = fast_scalp_min_gross_usd(stake, lev, mode_id="mega")
        mega_live._mega_positions = [
            {
                "symbol": "APTUSDT",
                "stake_usd": stake,
                "leverage": lev,
                "max_unreal_seen": flash + 1.0,
                "unrealized_pnl": 1.5,
                "tp_net_target_usd": 20.0,
            }
        ]
        env = {"MEGA_MARK_SPIKE": "1", "MEGA_FAST_EXIT_MARK_FRAC": "0.78"}
        with patch.dict(os.environ, env, clear=False):
            self.assertTrue(mega_live.mega_needs_fast_exit())


class MegaOpenFastPollTests(unittest.TestCase):
    def test_mega_has_open_when_cache_or_local(self) -> None:
        from elite_trader import mega_live

        mega_live._mega_positions = []
        mega_live._mega_positions_cache = [{"coin": "APT", "side": "LONG"}]
        env = {"MEGA_LIVE_ORDERS": "1", "MEGA_BINANCE_API_KEY": "k", "MEGA_BINANCE_API_SECRET": "s"}
        with patch.dict(os.environ, env, clear=False):
            mega_live._mega_client = None
            self.assertTrue(mega_live.mega_has_open())


class MegaMinCloseNetTests(unittest.TestCase):
    def test_profit_seen_blocks_below_net_floor(self) -> None:
        from elite_trader import mega_live

        # gross ~6 → cüzdan net ~4 (< MEGA_MIN_CLOSE_NET_USD=5)
        pos = {
            "max_unreal_seen": 6.0,
            "max_net_seen": 3.98,
            "unrealized_pnl": 5.0,
            "stake_usd": 510.0,
            "leverage": 5,
            "entry_fee": 1.0,
        }
        with patch.dict(
            os.environ,
            {"MEGA_MIN_CLOSE_NET_USD": "5", "MEGA_EXIT_MIN_NET_USD": "5"},
            clear=False,
        ):
            self.assertFalse(
                mega_live._mega_profit_seen_ok(pos, exit_reason="TP-PEAK")
            )

    def test_profit_seen_allows_at_net_floor(self) -> None:
        from elite_trader import mega_live

        pos = {
            "max_unreal_seen": 12.0,
            "max_net_seen": 5.5,
            "unrealized_pnl": 5.0,
            "stake_usd": 510.0,
            "leverage": 5,
            "entry_fee": 1.0,
        }
        with patch.dict(
            os.environ,
            {"MEGA_MIN_CLOSE_NET_USD": "5", "MEGA_EXIT_MIN_NET_USD": "5"},
            clear=False,
        ):
            self.assertTrue(mega_live._mega_profit_seen_ok(pos, exit_reason="TP"))

    def test_mark_spike_requires_net_floor(self) -> None:
        from elite_trader import mega_live

        pos = {
            "unrealized_pnl": 8.0,
            "stake_usd": 510.0,
            "leverage": 5,
            "entry_fee": 1.0,
        }
        env = {
            "MEGA_MARK_SPIKE": "1",
            "MEGA_MIN_CLOSE_NET_USD": "5",
            "MEGA_EXIT_MIN_NET_USD": "5",
        }
        with patch.dict(os.environ, env, clear=False):
            with patch.object(
                mega_live,
                "_mega_estimated_wallet_net",
                return_value=4.5,
            ):
                self.assertFalse(
                    mega_live._mega_mark_spike_ready(pos, stake=510.0, lev=5)
                )
            with patch.object(
                mega_live,
                "_mega_estimated_wallet_net",
                return_value=5.2,
            ):
                self.assertTrue(
                    mega_live._mega_mark_spike_ready(pos, stake=510.0, lev=5)
                )


class MegaUnderwaterTimeStopTests(unittest.TestCase):
    def test_underwater_cut_after_age(self) -> None:
        from elite_trader import mega_live

        pos = {
            "opened_at_iso": "2026-05-29T20:00:00+00:00",
            "unrealized_pnl": -4.0,
            "max_unreal_seen": 2.0,
            "tp_net_target_usd": 20.0,
        }
        env = {
            "MEGA_UNDERWATER_CUT": "1",
            "MEGA_UNDERWATER_MAX_SEC": "60",
            "MEGA_UNDERWATER_MIN_LOSS_USD": "1.5",
        }
        with patch.dict(os.environ, env, clear=False):
            with patch(
                "elite_trader.panel_strategy.position_age_seconds", return_value=120.0
            ):
                reason = mega_live._mega_underwater_time_stop_reason(pos)
        self.assertEqual(reason, "TIME-STOP")

    def test_underwater_skip_when_peak_near_net_tp(self) -> None:
        from elite_trader import mega_live

        pos = {
            "opened_at_iso": "2026-05-29T20:00:00+00:00",
            "unrealized_pnl": -5.0,
            "max_unreal_seen": 9.0,
            "tp_net_target_usd": 20.0,
        }
        env = {"MEGA_UNDERWATER_CUT": "1", "MEGA_UNDERWATER_MAX_SEC": "60"}
        with patch.dict(os.environ, env, clear=False):
            with patch(
                "elite_trader.panel_strategy.position_age_seconds", return_value=120.0
            ):
                reason = mega_live._mega_underwater_time_stop_reason(pos)
        self.assertIsNone(reason)


class MegaLossCutExitTests(unittest.TestCase):
    """Underwater TIME-STOP + SL — evaluate_mega_exits ve allow_position_close."""

    def test_allow_time_stop_when_underwater_cut_on(self) -> None:
        from elite_trader.fee_economics import allow_position_close

        pos = {
            "on_exchange": True,
            "symbol": "XRPUSDT",
            "side": "LONG",
            "stake_usd": 400.0,
            "leverage": 5,
            "unrealized_pnl": -6.0,
        }
        env = {"MEGA_UNDERWATER_CUT": "1", "MEGA_DISABLE_SL_EXIT": "1"}
        with patch.dict(os.environ, env, clear=False):
            self.assertTrue(
                allow_position_close(
                    gross_unreal=-6.0,
                    stake_usd=400.0,
                    leverage=5,
                    exit_reason="TIME-STOP",
                    mode_id="mega",
                    pos=pos,
                )
            )

    def test_allow_sl_when_sl_exit_enabled(self) -> None:
        from elite_trader.fee_economics import allow_position_close

        pos = {
            "on_exchange": True,
            "symbol": "LINKUSDT",
            "side": "LONG",
            "stake_usd": 500.0,
            "leverage": 5,
        }
        with patch.dict(os.environ, {"MEGA_DISABLE_SL_EXIT": "0"}, clear=False):
            self.assertTrue(
                allow_position_close(
                    gross_unreal=-12.0,
                    stake_usd=500.0,
                    leverage=5,
                    exit_reason="SL",
                    mode_id="mega",
                    pos=pos,
                )
            )

    def test_sl_exit_when_disable_flag_off(self) -> None:
        from elite_trader.panel_strategy import evaluate_position_exit

        with patch.dict(os.environ, {"MEGA_DISABLE_SL_EXIT": "0"}, clear=False):
            reason = evaluate_position_exit(
                opened_at="2020-01-01T00:00:00+00:00",
                unrealized_usd=-50.0,
                tp_target_usd=45.0,
                sl_target_usd=5.0,
                stake_usd=1000.0,
                mode_id="mega",
            )
        self.assertEqual(reason, "SL")

    def test_evaluate_mega_exits_fires_underwater_close(self) -> None:
        from elite_trader import mega_live

        pos = {
            "id": 90001,
            "symbol": "INJUSDT",
            "side": "LONG",
            "stake_usd": 400.0,
            "leverage": 5,
            "unrealized_pnl": -5.0,
            "max_unreal_seen": 1.0,
            "tp_net_target_usd": 18.0,
            "opened_at_iso": "2026-06-01T12:00:00+00:00",
            "on_exchange": True,
        }
        env = {
            "MEGA_UNDERWATER_CUT": "1",
            "MEGA_UNDERWATER_MAX_SEC": "45",
            "MEGA_UNDERWATER_MIN_LOSS_USD": "1.5",
        }
        closed: list[tuple[int, str]] = []

        def _fake_close(pid: int, reason: str) -> bool:
            closed.append((pid, reason))
            return True

        with patch.dict(os.environ, env, clear=False):
            with patch.object(mega_live, "_mega_positions", [pos]):
                with patch.object(mega_live, "_mega_positions_cache", []):
                    with patch.object(mega_live, "mega_motor_active", return_value=True):
                        with patch.object(mega_live, "get_mega_client", return_value=None):
                            with patch.object(
                                mega_live, "touch_mega_cache_from_hub_marks"
                            ):
                                with patch.object(
                                    mega_live, "_sync_pos_from_exchange"
                                ):
                                    with patch.object(
                                        mega_live,
                                        "_mega_api_gross_unreal",
                                        return_value=-5.0,
                                    ):
                                        with patch.object(
                                            mega_live,
                                            "_mega_touch_peak_net",
                                        ):
                                            with patch.object(
                                                mega_live,
                                                "_mega_update_profit_tier_lock",
                                            ):
                                                with patch.object(
                                                    mega_live,
                                                    "close_mega_position",
                                                    side_effect=_fake_close,
                                                ):
                                                    with patch(
                                                        "elite_trader.panel_strategy.position_age_seconds",
                                                        return_value=120.0,
                                                    ):
                                                        mega_live.evaluate_mega_exits(
                                                            {"INJUSDT": 12.0}
                                                        )
        self.assertEqual(closed, [(90001, "TIME-STOP")])


class MegaMarkSpikeTests(unittest.TestCase):
    def test_mark_spike_triggers_at_net_floor(self) -> None:
        from elite_trader import mega_live
        from elite_trader.fee_economics import fast_scalp_min_gross_usd

        stake, lev = 510.0, 5
        flash = fast_scalp_min_gross_usd(stake, lev, mode_id="mega")
        # flash brüt ~4.6 yetmez; cüzdan net ≥5 için brüt ~7+ gerekir (510×5 stake)
        gross_at_net5 = 7.34
        self.assertGreaterEqual(gross_at_net5, flash)
        pos = {
            "opened_at_iso": "2026-05-29T20:00:00+00:00",
            "unrealized_pnl": gross_at_net5,
            "max_unreal_seen": gross_at_net5,
            "stake_usd": stake,
            "leverage": lev,
            "entry_fee": 1.0,
        }
        env = {
            "MEGA_MARK_SPIKE": "1",
            "MEGA_MIN_CLOSE_NET_USD": "5",
            "MEGA_EXIT_MIN_NET_USD": "5",
        }
        with patch.dict(os.environ, env, clear=False):
            with patch(
                "elite_trader.panel_strategy.position_age_seconds", return_value=2.0
            ):
                reason = mega_live._mega_mark_spike_reason(
                    pos, stake=stake, lev=lev
                )
        self.assertEqual(reason, "SPIKE-FLASH")

    def test_mark_spike_skips_below_flash(self) -> None:
        from elite_trader import mega_live

        pos = {
            "opened_at_iso": "2026-05-29T20:00:00+00:00",
            "unrealized_pnl": 3.0,
            "stake_usd": 510.0,
            "leverage": 5,
            "entry_fee": 1.0,
        }
        with patch.dict(os.environ, {"MEGA_MARK_SPIKE": "1"}, clear=False):
            with patch(
                "elite_trader.panel_strategy.position_age_seconds", return_value=2.0
            ):
                reason = mega_live._mega_mark_spike_reason(
                    pos, stake=510.0, lev=5
                )
        self.assertIsNone(reason)


class MegaSpikeGrossOnlyTests(unittest.TestCase):
    def test_mega_skips_gross_flash_without_net_when_mark_spike_off(self) -> None:
        from elite_trader.panel_strategy import _spike_reason_mode

        env = {
            "MEGA_SPIKE_QUICK": "1",
            "MEGA_SPIKE_GROSS_ONLY": "0",
            "MEGA_MARK_SPIKE": "0",
        }
        with patch.dict(os.environ, env, clear=False):
            with patch(
                "elite_trader.fee_economics.net_scalp_close_ready",
                return_value=(False, 0.5, 2.5),
            ):
                reason = _spike_reason_mode(
                    mode_id="mega",
                    opened_at="2026-05-29T20:00:00+00:00",
                    unrealized_usd=7.0,
                    tp_target_usd=22.0,
                    stake_usd=510.0,
                    max_unreal_seen=7.0,
                    leverage=5,
                )
        self.assertEqual(reason, "")

    def test_mega_gross_flash_when_mark_spike_on(self) -> None:
        from elite_trader.panel_strategy import _spike_reason_mode
        from elite_trader.fee_economics import fast_scalp_min_gross_usd

        stake, lev = 510.0, 5
        flash = fast_scalp_min_gross_usd(stake, lev, mode_id="mega")
        env = {"MEGA_MARK_SPIKE": "1", "MEGA_SPIKE_GROSS_ONLY": "1"}
        with patch.dict(os.environ, env, clear=False):
            with patch(
                "elite_trader.panel_strategy.position_age_seconds", return_value=2.0
            ):
                reason = _spike_reason_mode(
                    mode_id="mega",
                    opened_at="2026-05-29T20:00:00+00:00",
                    unrealized_usd=flash + 0.2,
                    tp_target_usd=22.0,
                    stake_usd=stake,
                    max_unreal_seen=flash + 0.2,
                    leverage=lev,
                )
        self.assertEqual(reason, "SPIKE-FLASH")


class MegaProfitSendFillTests(unittest.TestCase):
    def test_fill_slippage_strict_rejects_zero_fill(self) -> None:
        from elite_trader.exchange_fill_truth import fill_slippage_reject

        self.assertTrue(
            fill_slippage_reject(32.0, 0.0, pre_send_gross=32.0, strict=True)
        )
        self.assertTrue(
            fill_slippage_reject(32.0, 2.0, pre_send_gross=32.0, strict=True)
        )
        self.assertFalse(
            fill_slippage_reject(32.0, 18.0, pre_send_gross=32.0, strict=True)
        )

    def test_clear_fill_verify_cache(self) -> None:
        from elite_trader.exchange_fill_truth import clear_fill_verify_cache

        pos = {"fill_verify_ok": True, "fill_net_est": 12.0}
        clear_fill_verify_cache(pos)
        self.assertNotIn("fill_verify_ok", pos)

    def test_market_fallback_env_off(self) -> None:
        from elite_trader import mega_live

        with patch.dict(os.environ, {"MEGA_PROFIT_CLOSE_MARKET_FALLBACK": "0"}, clear=False):
            self.assertFalse(mega_live._mega_profit_close_market_fallback())


class MegaPhantomCloseGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        from elite_trader import mega_live

        mega_live._phantom_close_guard.clear()

    def test_phantom_slippage_detected_after_peak_profit(self) -> None:
        from elite_trader import mega_live

        pos = {
            "symbol": "INJUSDT",
            "side": "LONG",
            "max_unreal_seen": 15.37,
            "pre_send_net": 11.12,
        }
        settled = {"wallet_pnl": -2.94, "net_pnl": -2.94}
        self.assertTrue(
            mega_live._mega_phantom_slippage_detected(
                pos, "SYNC-EXCHANGE", "EXCHANGE-SYNC", settled
            )
        )
        self.assertFalse(
            mega_live._mega_skip_phantom_closed_record(
                pos, "SYNC-EXCHANGE", "EXCHANGE-SYNC", settled
            )
        )

    def test_phantom_meta_tags_panel_hide(self) -> None:
        from elite_trader import mega_live

        pos = {
            "symbol": "DOGEUSDT",
            "side": "SHORT",
            "pre_send_net": 36.0,
            "pre_send_gross": 43.0,
        }
        settled = {"wallet_pnl": -14.59, "net_pnl": -14.59}
        closed = {"symbol": "DOGEUSDT", "side": "SHORT", "wallet_pnl": -14.59}
        out = mega_live._apply_phantom_slippage_meta(
            closed,
            pos,
            exit_reason="SPIKE-FLASH",
            record_reason="SPIKE-FLASH",
            exchange_settled=settled,
        )
        self.assertTrue(out.get("phantom_slippage"))
        self.assertTrue(out.get("panel_hide"))

    def test_phantom_guard_blocks_repeat(self) -> None:
        from elite_trader import mega_live

        pos = {"symbol": "INJUSDT", "side": "LONG", "max_unreal_seen": 0}
        mega_live._register_phantom_close_guard(pos, ttl_sec=120.0)
        self.assertTrue(mega_live._phantom_guard_active("INJUSDT", "LONG"))
        self.assertTrue(
            mega_live._mega_skip_phantom_closed_record(
                pos, "SYNC-EXCHANGE", "EXCHANGE-SYNC", {"wallet_pnl": -1.0}
            )
        )


class MegaSyncExitReasonTests(unittest.TestCase):
    def test_vanished_not_tp_when_fill_far_from_stop(self) -> None:
        from elite_trader import mega_live

        pos = {
            "exchange_tp_order_id": "1000000090088384",
            "exchange_tp_stop": 6.63215,
            "side": "LONG",
        }
        settled = {"exit_price": 6.602, "wallet_pnl": -1.37, "close_order_id": ""}
        self.assertEqual(
            mega_live._infer_vanished_exit_reason(pos, settled), "SYNC-EXCHANGE"
        )

    def test_vanished_tp_when_fill_matches_stop(self) -> None:
        from elite_trader import mega_live

        pos = {
            "exchange_tp_order_id": "1000000090088384",
            "exchange_tp_stop": 6.63215,
            "side": "LONG",
        }
        settled = {
            "exit_price": 6.6321,
            "wallet_pnl": 8.0,
            "close_order_id": "1000000090088384",
        }
        self.assertEqual(mega_live._infer_vanished_exit_reason(pos, settled), "TP")

    def test_exchange_tp_skips_fee_kill_stop(self) -> None:
        from elite_trader import mega_live

        pos = {
            "entry_price": 6.601,
            "size": 835.2,
            "side": "LONG",
            "stake_usd": 574.0,
            "leverage": 10,
            "entry_fee": 2.2,
        }
        with patch.dict(
            os.environ,
            {"MEGA_MIN_CLOSE_NET_USD": "5", "MEGA_EXIT_MIN_NET_USD": "5"},
            clear=False,
        ):
            self.assertFalse(mega_live._mega_exchange_tp_net_ok(pos, 6.602))
            self.assertTrue(mega_live._mega_exchange_tp_net_ok(pos, 6.632))


class MegaPeakSpikeTests(unittest.TestCase):
    def test_peak_spike_at_high_when_net_floor_met(self) -> None:
        from elite_trader import mega_live

        pos = {
            "max_unreal_seen": 22.0,
            "max_net_seen": 14.0,
            "unrealized_pnl": 21.5,
            "stake_usd": 1000.0,
            "leverage": 10,
            "entry_fee": 4.0,
            "side": "LONG",
        }
        env = {
            "MEGA_MARK_SPIKE": "1",
            "MEGA_MIN_CLOSE_NET_USD": "10",
            "MEGA_SPIKE_PEAK_FRAC": "0.97",
        }
        with patch.dict(os.environ, env, clear=False):
            self.assertTrue(
                mega_live._mega_peak_spike_ready(pos, stake=1000.0, lev=10)
            )

    def test_peak_spike_blocks_after_retrace(self) -> None:
        from elite_trader import mega_live

        pos = {
            "max_unreal_seen": 22.0,
            "max_net_seen": 14.0,
            "unrealized_pnl": 12.0,
            "stake_usd": 1000.0,
            "leverage": 10,
            "entry_fee": 4.0,
            "side": "LONG",
        }
        env = {"MEGA_MARK_SPIKE": "1", "MEGA_MIN_CLOSE_NET_USD": "10"}
        with patch.dict(os.environ, env, clear=False):
            self.assertFalse(
                mega_live._mega_peak_spike_ready(pos, stake=1000.0, lev=10)
            )


class MegaSnapshotHybridTests(unittest.TestCase):
    def test_hybrid_charts_light_skips_fetch_full_fetches(self) -> None:
        from elite_trader import mega_live

        env = {"MEGA_SNAPSHOT_CHARTS": "0", "MEGA_SNAPSHOT_CHARTS_HYBRID": "1"}
        with patch.dict(os.environ, env, clear=False):
            self.assertFalse(mega_live._mega_snapshot_allow_charts(light=True))
            self.assertTrue(mega_live._mega_snapshot_allow_charts(light=False))

    def test_legacy_charts_always_on(self) -> None:
        from elite_trader import mega_live

        env = {"MEGA_SNAPSHOT_CHARTS": "1", "MEGA_SNAPSHOT_CHARTS_HYBRID": "1"}
        with patch.dict(os.environ, env, clear=False):
            self.assertTrue(mega_live._mega_snapshot_allow_charts(light=True))
            self.assertTrue(mega_live._mega_snapshot_allow_charts(light=False))

    def test_hybrid_disabled_charts_off(self) -> None:
        from elite_trader import mega_live

        env = {"MEGA_SNAPSHOT_CHARTS": "0", "MEGA_SNAPSHOT_CHARTS_HYBRID": "0"}
        with patch.dict(os.environ, env, clear=False):
            self.assertFalse(mega_live._mega_snapshot_allow_charts(light=True))
            self.assertFalse(mega_live._mega_snapshot_allow_charts(light=False))


class MegaSnapshotUiCacheTests(unittest.TestCase):
    def test_light_snapshot_reuses_ui_cache(self) -> None:
        from elite_trader import mega_live

        mega_live._mega_open_ui_cache = None
        mega_live._mega_positions = [
            {
                "id": 1,
                "symbol": "BTCUSDT",
                "side": "LONG",
                "entry_price": 100.0,
                "current_price": 101.0,
                "unrealized_pnl": 5.0,
                "stake_usd": 500.0,
                "leverage": 5,
            }
        ]
        mega_live._mega_positions_cache = [
            {"coin": "BTC", "symbol": "BTCUSDT", "side": "LONG", "contracts": 1.0}
        ]
        calls: list[bool] = []

        def _fake_build(**kwargs):
            calls.append(kwargs.get("light", False))
            return [{"id": 1, "symbol": "BTCUSDT", "current_price": 101.0}]

        with patch.object(mega_live, "_build_mega_open_for_ui", side_effect=_fake_build):
            r1 = mega_live._open_rows_for_snapshot(light=True, allow_charts=False)
            r2 = mega_live._open_rows_for_snapshot(light=True, allow_charts=False)
        self.assertEqual(len(calls), 1)
        self.assertEqual(r1[0]["symbol"], "BTCUSDT")
        self.assertEqual(r2[0]["symbol"], "BTCUSDT")


class MegaTrailLockTests(unittest.TestCase):
    def test_trail_lock_target_scales_with_peak(self) -> None:
        from elite_trader import mega_live

        pos = {
            "max_unreal_seen": 20.0,
            "tp_net_target_usd": 40.0,
            "entry_price": 100.0,
            "size": 100.0,
            "side": "LONG",
            "stake_usd": 1000.0,
            "leverage": 10,
            "entry_fee": 0.8,
        }
        with patch.dict(
            os.environ,
            {
                "MEGA_EXCHANGE_DUAL_TP": "1",
                "MEGA_EXCHANGE_ARM_GROSS_USD": "1.5",
                "MEGA_EXCHANGE_ARM_NET": "3",
                "MEGA_TRAIL_LOCK_MIN_NET": "3",
                "MEGA_TRAIL_LOCK_RETRACE_FRAC": "0.97",
            },
            clear=False,
        ):
            target = mega_live._mega_trail_lock_target_net(pos, mc=None)
        self.assertIsNotNone(target)
        assert target is not None
        self.assertGreaterEqual(target, 3.0)
        self.assertLessEqual(target, 40.0)

    def test_dynamic_tp_ceiling_between_peak_and_full(self) -> None:
        from elite_trader import mega_live

        pos = {
            "max_unreal_seen": 12.0,
            "tp_net_target_usd": 40.0,
            "entry_price": 100.0,
            "size": 100.0,
            "side": "LONG",
            "stake_usd": 1000.0,
            "leverage": 10,
            "entry_fee": 0.8,
        }
        with patch.dict(
            os.environ,
            {
                "MEGA_EXCHANGE_DUAL_TP": "1",
                "MEGA_EXCHANGE_ARM_NET": "3",
                "MEGA_EXCHANGE_TP_RUNWAY_FRAC": "0.42",
            },
            clear=False,
        ):
            lock = mega_live._mega_trail_lock_target_net(pos, mc=None)
            ceiling = mega_live._mega_dynamic_tp_ceiling_net(pos, mc=None)
        self.assertIsNotNone(lock)
        self.assertIsNotNone(ceiling)
        assert lock is not None and ceiling is not None
        self.assertGreater(ceiling, lock)
        self.assertLessEqual(ceiling, 40.0)

    def test_simple_dual_tp_floor_and_full_target(self) -> None:
        from elite_trader import mega_live

        pos = {
            "max_unreal_seen": 12.0,
            "max_net_seen": 9.0,
            "tp_net_target_usd": 40.0,
            "entry_price": 100.0,
            "current_price": 100.12,
            "size": 100.0,
            "side": "LONG",
            "stake_usd": 1000.0,
            "leverage": 10,
            "entry_fee": 0.8,
        }
        with patch.dict(
            os.environ,
            {
                "MEGA_EXCHANGE_DUAL_TP": "1",
                "MEGA_EXCHANGE_SIMPLE_DUAL_TP": "1",
                "MEGA_EXCHANGE_FLOOR_NET": "8",
            },
            clear=False,
        ):
            self.assertTrue(mega_live._mega_floor_net_armed(pos, mc=None))
            lock = mega_live._mega_trail_lock_target_net(pos, mc=None)
            tp_gross = mega_live._mega_tp_gross_candidate(pos, mc=None)
            tp_net = mega_live._mega_dynamic_tp_ceiling_net(pos, mc=None)
        self.assertIsNotNone(lock)
        assert lock is not None
        self.assertGreaterEqual(lock, 8.0)
        self.assertIsNotNone(tp_gross)
        self.assertEqual(tp_net, 40.0)

    def test_simple_lock_not_armed_below_floor(self) -> None:
        from elite_trader import mega_live

        pos = {
            "max_unreal_seen": 3.0,
            "tp_net_target_usd": 40.0,
            "entry_price": 100.0,
            "current_price": 100.01,
            "size": 100.0,
            "side": "LONG",
            "stake_usd": 1000.0,
            "leverage": 10,
        }
        with patch.dict(
            os.environ,
            {
                "MEGA_EXCHANGE_DUAL_TP": "1",
                "MEGA_EXCHANGE_SIMPLE_DUAL_TP": "1",
                "MEGA_EXCHANGE_FLOOR_NET": "8",
            },
            clear=False,
        ):
            self.assertFalse(mega_live._mega_floor_net_armed(pos, mc=None))
            self.assertIsNone(mega_live._mega_trail_lock_target_net(pos, mc=None))
            self.assertIsNotNone(mega_live._mega_tp_gross_candidate(pos, mc=None))

    def test_lock_gross_never_decreases(self) -> None:
        from elite_trader import mega_live

        pos = {
            "max_unreal_seen": 10.0,
            "exchange_lock_gross": 8.5,
            "entry_price": 100.0,
            "size": 100.0,
            "side": "LONG",
        }
        with patch.dict(
            os.environ,
            {
                "MEGA_EXCHANGE_DUAL_TP": "1",
                "MEGA_EXCHANGE_ARM_GROSS_USD": "1.5",
                "MEGA_TRAIL_LOCK_RETRACE_FRAC": "0.99",
            },
            clear=False,
        ):
            gross = mega_live._mega_lock_gross_candidate(pos)
        self.assertIsNotNone(gross)
        assert gross is not None
        self.assertGreaterEqual(gross, 8.5)

    def test_lock_net_monotonic_with_prev(self) -> None:
        from elite_trader import mega_live

        pos = {
            "max_unreal_seen": 20.0,
            "exchange_lock_net": 6.0,
            "tp_net_target_usd": 40.0,
            "entry_price": 100.0,
            "size": 100.0,
            "side": "LONG",
            "stake_usd": 1000.0,
            "leverage": 10,
            "entry_fee": 0.8,
        }
        with patch.dict(
            os.environ,
            {
                "MEGA_EXCHANGE_DUAL_TP": "0",
                "MEGA_TRAIL_LOCK_ARM_NET": "3",
                "MEGA_TRAIL_LOCK_MIN_NET": "3",
                "MEGA_TRAIL_LOCK_RETRACE_FRAC": "0.97",
            },
            clear=False,
        ):
            target = mega_live._mega_trail_lock_target_net(pos, mc=None)
        self.assertIsNotNone(target)
        assert target is not None
        self.assertGreaterEqual(target, 6.0)

    def test_stop_not_degraded_long(self) -> None:
        from elite_trader import mega_live

        pos = {"side": "LONG"}
        self.assertTrue(mega_live._mega_stop_not_degraded(pos, 101.0, 100.0))
        self.assertFalse(mega_live._mega_stop_not_degraded(pos, 99.5, 100.0))

    def test_trail_lock_not_armed_below_min(self) -> None:
        from elite_trader import mega_live

        pos = {
            "max_unreal_seen": 5.0,
            "entry_price": 100.0,
            "size": 100.0,
            "side": "LONG",
            "stake_usd": 1000.0,
            "leverage": 10,
        }
        with patch.dict(
            os.environ,
            {
                "MEGA_EXCHANGE_DUAL_TP": "0",
                "MEGA_TRAIL_LOCK_ARM_NET": "8",
                "MEGA_TRAIL_LOCK_MIN_NET": "8",
            },
            clear=False,
        ):
            self.assertIsNone(mega_live._mega_trail_lock_target_net(pos, mc=None))

    def test_trail_stop_long_below_mark(self) -> None:
        from elite_trader import mega_live

        pos = {
            "entry_price": 100.0,
            "current_price": 101.5,
            "size": 100.0,
            "side": "LONG",
            "stake_usd": 1000.0,
            "leverage": 10,
            "entry_fee": 0.8,
        }
        with patch.dict(
            os.environ,
            {"MEGA_TRAIL_LOCK_MIN_NET": "8", "MEGA_TRAIL_LOCK_MAX_NET": "15"},
            clear=False,
        ):
            stop = mega_live._mega_trail_stop_from_lock_net(pos, 10.0, mc=None)
            self.assertGreater(stop, 100.0)
            self.assertLess(stop, 101.5)
            self.assertTrue(mega_live._mega_trail_stop_valid(pos, stop, mc=None))

    def test_tp_lock_milestones_from_tp_target(self) -> None:
        from elite_trader import mega_live

        pos = {"tp_net_target_usd": 20.0}
        with patch.dict(
            os.environ,
            {
                "MEGA_TRAIL_LOCK_MIN_NET": "8",
                "MEGA_TRAIL_LOCK_MAX_NET": "15",
                "MEGA_TP_LOCK_MILESTONE_FRAC": "0.25,0.50,0.75",
            },
            clear=False,
        ):
            levels = mega_live._mega_tp_lock_milestones(pos)
        self.assertEqual(levels, [8.0, 10.0, 15.0])

    def test_milestone_advanced_triggers_lock_update(self) -> None:
        from elite_trader import mega_live

        pos = {
            "tp_net_target_usd": 20.0,
            "exchange_lock_milestone": 8.0,
            "side": "LONG",
        }
        with patch.dict(
            os.environ,
            {"MEGA_TRAIL_LOCK_MIN_NET": "8", "MEGA_TRAIL_LOCK_MAX_NET": "15"},
            clear=False,
        ):
            self.assertTrue(mega_live._mega_trail_milestone_advanced(pos, 12.0))
            self.assertFalse(mega_live._mega_trail_milestone_advanced(pos, 8.5))

    def test_sanitize_lock_stop_short_above_mark(self) -> None:
        from elite_trader import mega_live

        class FakeMc:
            def round_price(self, coin: str, p: float) -> float:
                return round(p, 4)

        pos = {"side": "SHORT", "symbol": "XRPUSDT", "current_price": 2.0}
        with patch.dict(os.environ, {"MEGA_TRAIL_LOCK_MARK_BUMP_PCT": "0.0025"}, clear=False):
            stop = mega_live._mega_sanitize_lock_stop(pos, 2.001, FakeMc())
        self.assertGreaterEqual(stop, 2.0 * 1.0025)

    def test_mega_exchange_mark_arm_ok_small_peak(self) -> None:
        from elite_trader.mega_live import _mega_exchange_mark_arm_ok

        with patch.dict(
            os.environ,
            {"MEGA_EXCHANGE_ARM_GROSS_USD": "0.8"},
            clear=False,
        ):
            pos = {
                "max_unreal_seen": 1.2,
                "exchange_unrealized_pnl": 1.0,
                "unrealized_pnl": 1.0,
            }
            ok, _ = _mega_exchange_mark_arm_ok(pos)
            self.assertTrue(ok)
            pos2 = {"max_unreal_seen": 0.3, "exchange_unrealized_pnl": 0.2}
            ok2, _ = _mega_exchange_mark_arm_ok(pos2)
            self.assertFalse(ok2)

    def test_mega_blocks_sl_close_reasons(self) -> None:
        from elite_trader.mega_live import mega_blocks_sl_close

        with patch.dict(os.environ, {"MEGA_DISABLE_SL_EXIT": "1"}, clear=False):
            self.assertTrue(mega_blocks_sl_close("SL"))
            self.assertTrue(mega_blocks_sl_close("SL-EMERGENCY"))
            self.assertTrue(mega_blocks_sl_close("NET-LOSS"))
            self.assertTrue(mega_blocks_sl_close("TIME-STOP"))
            self.assertFalse(mega_blocks_sl_close("TP"))
            self.assertFalse(mega_blocks_sl_close("SPIKE-FLASH"))
            self.assertFalse(mega_blocks_sl_close("MANUAL"))
        with patch.dict(os.environ, {"MEGA_DISABLE_SL_EXIT": "0"}, clear=False):
            self.assertFalse(mega_blocks_sl_close("SL"))

    def test_mega_sl_exit_disabled_by_default(self) -> None:
        from elite_trader.panel_strategy import evaluate_position_exit

        with patch.dict(os.environ, {"MEGA_DISABLE_SL_EXIT": "1"}, clear=False):
            reason = evaluate_position_exit(
                opened_at="2020-01-01T00:00:00+00:00",
                unrealized_usd=-50.0,
                tp_target_usd=45.0,
                sl_target_usd=5.0,
                stake_usd=1000.0,
                mode_id="mega",
            )
        self.assertIsNone(reason)


class MegaClosedExchangeVerifyTests(unittest.TestCase):
    def test_phantom_oid_rejected(self) -> None:
        from elite_trader.exchange_trade_truth import closed_has_exchange_fill

        class FakeMc:
            paper = False

            def user_trades(self, coin, **kw):
                if coin == "DOGE":
                    return [
                        {
                            "orderId": "847067254",
                            "realizedPnl": "23.8152",
                            "side": "SELL",
                            "qty": "99230",
                            "quoteQty": "10021.23",
                            "commission": "4.008",
                            "time": 1780146130413,
                        }
                    ]
                return []

        mc = FakeMc()
        from elite_trader.exchange_trade_truth import build_exchange_close_index

        idx = build_exchange_close_index(mc, coins=["DOGE"])
        self.assertTrue(
            closed_has_exchange_fill(
                {
                    "on_exchange": True,
                    "symbol": "DOGEUSDT",
                    "side": "LONG",
                    "exchange_close_order_id": "847067254",
                    "wallet_pnl": 19.8,
                },
                mc,
                close_index=idx,
            )
        )
        self.assertFalse(
            closed_has_exchange_fill(
                {
                    "on_exchange": True,
                    "symbol": "LINKUSDT",
                    "side": "LONG",
                    "exchange_close_order_id": "575481826",
                    "wallet_pnl": 15.6,
                },
                mc,
                close_index=idx,
            )
        )


class MegaExchangeUpnlSyncTests(unittest.TestCase):
    def test_apply_price_tick_skips_on_exchange(self) -> None:
        from elite_trader import mega_live

        pos = {
            "symbol": "AVAXUSDT",
            "side": "LONG",
            "on_exchange": True,
            "entry_price": 8.946,
            "size": 1117.0,
            "stake_usd": 1000.0,
            "unrealized_pnl": 12.5,
            "exchange_unrealized_pnl": 12.5,
        }
        mega_live._apply_price_tick(pos, {"AVAX": 8.937})
        self.assertAlmostEqual(float(pos["unrealized_pnl"]), 12.5)
        self.assertAlmostEqual(float(pos["exchange_unrealized_pnl"]), 12.5)

    def test_sync_pos_from_exchange_overwrites_ws_last(self) -> None:
        from elite_trader import mega_live

        pos = {
            "symbol": "AVAXUSDT",
            "side": "LONG",
            "on_exchange": True,
            "entry_price": 8.946,
            "size": 1117.0,
            "stake_usd": 1000.0,
            "leverage": 10,
            "unrealized_pnl": -9.9,
            "min_unreal_seen": -9.9,
            "max_unreal_seen": -9.9,
        }
        exch = [
            {
                "coin": "AVAX",
                "symbol": "AVAXUSDT",
                "side": "LONG",
                "entry_price": 8.946,
                "mark_price": 8.957,
                "contracts": 1117.0,
                "leverage": 10,
                "unrealized_pnl": 12.287,
                "notional_usd": 9999.0,
                "exchange_raw": {
                    "entryPrice": "8.946",
                    "markPrice": "8.957",
                    "unRealizedProfit": "12.287",
                    "positionAmt": "1117",
                },
            }
        ]
        mega_live._sync_pos_from_exchange(pos, exch, mode_id="mega")
        self.assertAlmostEqual(float(pos["unrealized_pnl"]), 12.287)
        self.assertAlmostEqual(float(pos["exchange_unrealized_pnl"]), 12.287)
        self.assertAlmostEqual(float(pos["current_price"]), 8.957)


class MegaPeakTrackHubMarkTests(unittest.TestCase):
    def test_hub_mark_peak_without_changing_display_upnl(self) -> None:
        env = {
            "MEGA_LIVE_ORDERS": "1",
            "MEGA_BINANCE_API_KEY": "k",
            "MEGA_BINANCE_API_SECRET": "s",
            "MEGA_PANEL_EXCHANGE_ONLY": "1",
            "MEGA_PEAK_TRACK_HUB_MARK": "1",
            "MEGA_ASYNC_HUB": "1",
        }
        with patch.dict(os.environ, env, clear=False):
            from elite_trader import mega_live

            pos = {
                "symbol": "ETHUSDT",
                "side": "SHORT",
                "on_exchange": True,
                "entry_price": 1761.0,
                "size": 5.642,
                "stake_usd": 1000.0,
                "leverage": 10,
                "exchange_unrealized_pnl": 120.0,
                "unrealized_pnl": 120.0,
                "max_unreal_seen": 120.0,
                "max_exchange_unreal_seen": 120.0,
            }
            marks = {"ETH": 1720.0}
            with patch.object(mega_live, "_mega_peak_track_hub_mark_enabled", return_value=True):
                mega_live._mega_record_profit_peaks(pos, rest_gross=120.0, marks=marks)
            self.assertAlmostEqual(float(pos["unrealized_pnl"]), 120.0)
            self.assertAlmostEqual(float(pos["exchange_unrealized_pnl"]), 120.0)
            self.assertGreater(float(pos["max_mark_unreal_seen"]), 200.0)
            self.assertGreater(float(pos["max_unreal_seen"]), 200.0)
            self.assertAlmostEqual(float(pos["max_exchange_unreal_seen"]), 120.0)


class MegaSlClosedRecordTests(unittest.TestCase):
    def test_infer_exchange_sl_from_lock_order(self) -> None:
        from elite_trader import mega_live

        pos = {"exchange_lock_order_id": "99", "star_sl_exit": "SL-COIN25-BTC"}
        settled = {"close_order_id": "99", "wallet_pnl": -12.0, "pnl_usd": -10.0}
        self.assertEqual(
            mega_live._infer_exchange_sl_exit_reason(pos, settled), "SL-COIN25-BTC"
        )
        self.assertEqual(
            mega_live._infer_vanished_exit_reason(pos, settled), "SL-COIN25-BTC"
        )

    def test_bot_only_allows_sl_sync_backfill(self) -> None:
        from elite_trader import mega_live

        row = {
            "symbol": "SOLUSDT",
            "side": "LONG",
            "exit_reason": "SL",
            "wallet_pnl": -50.0,
            "backfilled": True,
            "sync_source": "exchange_userTrades",
        }
        with patch.object(mega_live, "mega_live_bot_only_closed", return_value=True):
            self.assertTrue(mega_live._mega_closed_persist_allowed(row))
        row_tp = dict(row, exit_reason="TP", wallet_pnl=8.0, sl_close=False)
        with patch.object(mega_live, "mega_live_bot_only_closed", return_value=True):
            self.assertFalse(mega_live._mega_closed_persist_allowed(row_tp))


class MegaExchangeVelocityTests(unittest.TestCase):
    def test_mark_velocity_hot_on_fast_move(self) -> None:
        from elite_trader.mega_live import (
            _mega_exchange_velocity_hot,
            _mega_track_mark_velocity,
        )

        pos: dict = {
            "symbol": "SOLUSDT",
            "side": "LONG",
            "entry_price": 100.0,
            "size": 10.0,
            "stake_usd": 1000,
            "leverage": 10,
        }
        with patch.dict(
            os.environ,
            {
                "MEGA_EXCHANGE_VELOCITY_TICK": "1",
                "MEGA_EXCHANGE_VELOCITY_MIN_USD_PER_SEC": "8",
            },
            clear=False,
        ):
            _mega_track_mark_velocity(pos, 100.0, 0.0)
            time.sleep(0.06)
            _mega_track_mark_velocity(pos, 100.5, 5.0)
            self.assertGreaterEqual(float(pos.get("hub_mark_velocity_usd_s") or 0), 8.0)
            self.assertTrue(_mega_exchange_velocity_hot(pos))

    def test_exchange_tick_interval_fast(self) -> None:
        from elite_trader.mega_live import _mega_exchange_tp_update_interval_sec

        with patch.dict(
            os.environ,
            {"MEGA_EXCHANGE_TP_UPDATE_FAST_SEC": "0.05"},
            clear=False,
        ):
            self.assertLessEqual(_mega_exchange_tp_update_interval_sec(fast=True), 0.06)


class MegaAsyncHubEnsureTests(unittest.TestCase):
    def test_ensure_starts_when_hub_missing(self) -> None:
        import elite_trader.mega_async_hub as hub_mod

        with patch.dict(os.environ, {"MEGA_ASYNC_HUB": "1"}, clear=False):
            hub_mod.stop_mega_async_hub()
            fake = object()
            with patch.object(hub_mod, "MegaAsyncHub") as MockHub:
                inst = MockHub.return_value
                inst.status.return_value = {"alive": False, "ready": False}
                hub_mod._hub = None
                hub_mod.ensure_mega_async_hub()
                MockHub.assert_called_once()
                inst.start.assert_called_once()
            hub_mod._hub = None

    def test_ensure_skipped_when_disabled(self) -> None:
        import elite_trader.mega_async_hub as hub_mod

        with patch.dict(os.environ, {"MEGA_ASYNC_HUB": "0"}, clear=False):
            with patch.object(hub_mod, "MegaAsyncHub") as MockHub:
                hub_mod.ensure_mega_async_hub()
                MockHub.assert_not_called()


if __name__ == "__main__":
    unittest.main()
