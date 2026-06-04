"""BERSERK2 dashboard metrikleri."""
from __future__ import annotations

from typing import Any

from elite_trader.berserk2_btc_context import get_btc_context
from elite_trader.berserk2_movers import movers_snapshot
from elite_trader.berserk_metrics import build_berserk_health
from elite_trader.panel_strategy import active_execution_mode, is_live_binance_motor


def build_berserk2_health(
    book: dict[str, Any],
    *,
    live_open: list[dict[str, Any]] | None = None,
    live_closed: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    base = build_berserk_health(book, live_open=live_open, live_closed=live_closed)
    exec_mid = active_execution_mode()
    base["mode_id"] = "berserk2"
    base["route"] = (
        "live"
        if is_live_binance_motor("berserk2") and exec_mid == "berserk2"
        else "paper"
    )
    base["top10_movers"] = movers_snapshot()
    base["btc_context"] = get_btc_context()
    return base
