"""mega_coin_rank — 24h sembol sıralama."""
from __future__ import annotations

import time

from elite_trader.mega_coin_rank import build_coin_rank


def _row(sym: str, stake: float, pnl: float, ts: float | None = None) -> dict:
    return {
        "symbol": sym,
        "stake_usd": stake,
        "wallet_pnl": pnl,
        "exit_time": ts or time.time(),
        "side": "LONG",
        "exit_reason": "TP",
    }


def test_rank_profit_yield_order_and_stars():
    now = time.time()
    rows = [
        _row("AAA", 1000, 50, now),
        _row("AAA", 1000, 30, now),
        _row("BBB", 500, -20, now),
        _row("CCC", 2000, 100, now),
        _row("DDD", 800, -40, now),
        _row("EEE", 600, 10, now),
    ]
    report = build_coin_rank(rows, window_hours=48.0)
    ranked = report["ranked"]
    assert ranked[0]["symbol"] == "CCC"
    assert report["stars"][0] == "CCC"
    assert len(report["stars"]) == 3
    assert len(report["bottom3"]) == 3
    assert "DDD" in report["bottom3"] or "BBB" in report["bottom3"]
