#!/usr/bin/env python3
"""One-off: panel position cache diagnostic (9006)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

env_path = ROOT / "scenarios" / "binance_elite_mega_9006_mainnet.env"
if env_path.is_file():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"'))

import binance_elite_pro as bep
import elite_trader.mega_live as ml


def main() -> None:
    print("LIVE_ORDERS", getattr(bep, "LIVE_ORDERS", None))
    cache = getattr(bep, "_positions_cache", None) or []
    print("elite cache n", len(cache))
    print("elite cache ts", getattr(bep, "_exchange_cache_ts", None))
    for ep in cache[:8]:
        print(
            " elite",
            ep.get("symbol"),
            ep.get("side"),
            ep.get("contracts"),
            ep.get("unrealizedPnl"),
            ep.get("notional_usd"),
        )

    print("mega cache n", len(getattr(ml, "_mega_positions_cache", None) or []))
    print("mega book n", len(getattr(ml, "_mega_positions", None) or []))
    print("panel ep rows", len(ml._panel_exchange_ep_rows()))
    print("elite rows fn", len(ml._elite_positions_rows()))

    ok = bep._refresh_positions_cache_only(
        force=True, timeout_sec=5.0, min_interval_sec=0.0
    )
    cache = bep._positions_cache or []
    print("refresh ok", ok, "n", len(cache))
    for ep in cache[:8]:
        print(
            " after",
            ep.get("symbol"),
            ep.get("side"),
            ep.get("contracts"),
            ep.get("unrealizedPnl"),
            ep.get("notional_usd"),
        )

    ing = ml.ingest_mega_positions_from_elite_poll(max_age_sec=30.0)
    print("ingest", ing, "mega cache", len(ml._mega_positions_cache or []))
    print("ensure fresh", ml._ensure_panel_position_risk_fresh())
    print("panel ep after", len(ml._panel_exchange_ep_rows()))
    filtered = ml._panel_exchange_ep_rows()
    from elite_trader.exchange_open_display import _filter_exchange_rows_for_panel

    print("filtered n", len(_filter_exchange_rows_for_panel(filtered)))
    payload = ml.panel_tick_http_payload()
    print("tick open", len(payload.get("open") or []))
    print("audit", payload.get("upnl_audit"))


if __name__ == "__main__":
    main()
