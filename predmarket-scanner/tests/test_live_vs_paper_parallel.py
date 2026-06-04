"""Live motor vs paper paralel evren — routing ve shadow kitap davranışı."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from elite_trader import parallel_universe_engine as pue


def _configure() -> None:
    pue.configure(
        edge_fn=lambda ch: abs(ch) * 0.01,
        formula_fn=lambda ch: min(1.0, abs(ch) * 0.02),
        kelly_fn=lambda ch, side: 200.0,
        min_edge=0.01,
        min_formula=0.01,
        session_start=5000.0,
        stake_bounds_fn=lambda: (100.0, 500.0),
        max_open_fn=lambda: 6,
        wr_fn=lambda: 0.5,
        leverage_fn=lambda s, d: 2,
        tradable_symbols={"BTCUSDT", "ETHUSDT"},
        scan_universe={"BTCUSDT", "ETHUSDT", "SOLUSDT"},
    )


def _signal() -> dict:
    return {
        "symbol": "SOLUSDT",
        "type": "LONG",
        "change": 0.45,
        "strength": "Medium",
    }


class TestLiveVsPaperParallel(unittest.TestCase):
    def test_live_motor_skips_paper_shadow(self):
        """Aktif live motor paralel paper kitabına yazmaz."""
        _configure()
        entry_calls: list[str] = []

        def track_entry(mode_id, signal, *, execution_path="paper"):
            entry_calls.append(mode_id)
            return False, "test_block"

        with patch.object(pue, "_entry_allowed", track_entry):
            with patch(
                "elite_trader.parallel_universe_engine.is_live_binance_motor",
                lambda mid: mid == "evrim",
            ):
                sig = _signal()
                pue.on_market_signal_for_mode("evrim", sig, 100.0)
                pue.on_market_signal_for_mode("sentinel", sig, 100.0)

        self.assertNotIn("evrim", entry_calls)
        self.assertIn("sentinel", entry_calls)

    def test_paper_mode_ids_excludes_live_motor(self):
        """paper_mode_ids() — yalnızca live motor hariç."""
        with patch(
            "elite_trader.panel_strategy.is_live_binance_motor",
            lambda mid: mid == "sentinel",
        ):
            ids = pue.paper_mode_ids()
        self.assertNotIn("sentinel", ids)
        self.assertIn("evrim", ids)
        self.assertIn("hunter", ids)

    def test_route_live_only_for_active_mode(self):
        """mode_id == active_futures_mode → LIVE route; diğerleri PAPER."""
        from elite_trader.order_gate import ORDER_ROUTE_LIVE, ORDER_ROUTE_PAPER, route_order

        intent = {"symbol": "BTCUSDT", "side": "LONG", "expected_net_pnl": 0.5}
        live = route_order(
            "sentinel",
            intent,
            active_futures_mode="sentinel",
            api_healthy=True,
            live_orders_enabled=True,
        )
        paper = route_order(
            "hunter",
            intent,
            active_futures_mode="sentinel",
            api_healthy=True,
            live_orders_enabled=True,
        )
        self.assertEqual(live.order_route, ORDER_ROUTE_LIVE)
        self.assertEqual(paper.order_route, ORDER_ROUTE_PAPER)
        self.assertTrue(paper.is_paper)

    def test_routing_status_lists_paper_modes(self):
        """get_routing_status — live + paper mod listesi."""
        from elite_trader.order_gate import get_routing_status

        st = get_routing_status("evrim")
        self.assertEqual(st["active_futures_mode"], "evrim")
        self.assertIn("sentinel", st["paper_modes"])
        self.assertNotIn("evrim", st["paper_modes"])
        self.assertFalse(st.get("live_motor_parallel_paper"))
        self.assertTrue(st.get("shared_market_feed"))

    def test_execution_mode_switch_does_not_mutate_profiles(self):
        """Motor seçimi mode_profiles.json dosyasını değiştirmez."""
        from elite_trader import panel_strategy as ps

        prof_path = _ROOT / "data" / "mode_profiles.json"
        before = prof_path.read_text(encoding="utf-8")
        orig_state = ps._STATE

        try:
            tmp = _ROOT / "data" / "backups" / "_test_panel_state_tmp.json"
            tmp.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(
                '{"execution_mode": "evrim", "view_mode": "evrim"}',
                encoding="utf-8",
            )
            ps._STATE = tmp
            self.assertEqual(ps.active_execution_mode(), "evrim")
            tmp.write_text(
                '{"execution_mode": "sentinel", "view_mode": "sentinel"}',
                encoding="utf-8",
            )
            self.assertEqual(ps.active_execution_mode(), "sentinel")
        finally:
            ps._STATE = orig_state
            if tmp.is_file():
                tmp.unlink()

        after = prof_path.read_text(encoding="utf-8")
        self.assertEqual(before, after)

    def test_on_market_signal_feeds_all_paper_modes(self):
        """on_market_signal — live motor hariç tüm paper modlara aday gönderir."""
        _configure()
        fed: list[str] = []

        def track(mode_id, signal, *, execution_path="paper"):
            fed.append(mode_id)
            return False, "test_block"

        with patch.object(pue, "_entry_allowed", track):
            with patch(
                "elite_trader.parallel_universe_engine.is_live_binance_motor",
                lambda mid: mid == "berserk",
            ):
                pue.on_market_signal(_signal(), 100.0)

        self.assertNotIn("berserk", fed)
        self.assertIn("evrim", fed)
        self.assertIn("sentinel", fed)
        self.assertIn("hunter", fed)


if __name__ == "__main__":
    unittest.main()
