"""Paper modlar — tam tarama evreni; live motor top-N çekirdek."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from elite_trader import parallel_universe_engine as pue


def _configure(tradable: set[str], scan: set[str]) -> None:
    pue.configure(
        edge_fn=lambda ch: abs(ch) * 0.001,
        formula_fn=lambda ch: min(1.0, abs(ch) * 0.01),
        kelly_fn=lambda ch, side: 200.0,
        min_edge=0.01,
        min_formula=0.01,
        session_start=5000.0,
        stake_bounds_fn=lambda: (100.0, 500.0),
        max_open_fn=lambda: 6,
        wr_fn=lambda: 0.5,
        leverage_fn=lambda s, d: 2,
        tradable_symbols=tradable,
        scan_universe=scan,
    )


def test_paper_allows_symbol_outside_tradable_core():
    _configure(tradable={"BTCUSDT", "ETHUSDT"}, scan={"BTCUSDT", "ETHUSDT", "PHBUSDT"})
    sig = {"symbol": "PHBUSDT", "type": "LONG", "change": 0.35, "strength": "Medium"}
    ok, reason = pue.entry_gate_for_mode("hunter", sig)
    assert ok or reason != "not in universe", reason


def test_live_motor_blocks_outside_tradable_core(monkeypatch):
    _configure(tradable={"BTCUSDT", "ETHUSDT"}, scan={"BTCUSDT", "ETHUSDT", "PHBUSDT"})
    monkeypatch.setattr(
        "elite_trader.panel_strategy.active_execution_mode",
        lambda: "evrim",
    )
    monkeypatch.setattr(
        "elite_trader.parallel_universe_engine.is_live_binance_motor",
        lambda mid: mid == "evrim",
    )
    sig = {"symbol": "PHBUSDT", "type": "LONG", "change": 0.35, "strength": "Medium"}
    ok, reason = pue.entry_gate_for_mode("evrim", sig)
    assert not ok
    assert reason == "not in universe"


def test_paper_reject_stats_recorded():
    pue.reset_paper_reject_stats()
    _configure(tradable={"BTCUSDT"}, scan={"BTCUSDT"})
    sig = {"symbol": "UNKNOWNUSDT", "type": "LONG", "change": 0.2, "strength": "Medium"}
    pue.on_market_signal_for_mode("hunter", sig, 1.0)
    stats = pue.paper_reject_stats().get("hunter") or {}
    assert stats.get("not in universe", 0) >= 1
