#!/usr/bin/env python3
"""Diagnose MEGA 9006 closed-trades pipeline."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except ImportError:
    pass

env_path = ROOT / "scenarios" / "binance_elite_mega_9006_mainnet.env"
if env_path.is_file():
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

os.environ.setdefault("MEGA_INSTANCE_ID", "9006")

from elite_trader import mega_live as ml
from elite_trader.mega_close_sync import sync_missing_closes_from_exchange

ml._ensure_mega_closed_loaded()
mc = ml.get_mega_client()
epoch = ml._closed_panel_epoch_sec()
since_ms = int(epoch * 1000) - 120_000
print("mega_live_enabled", ml.mega_live_enabled())
print("client_paper", getattr(mc, "paper", None) if mc else None)
print("panel_epoch", epoch, "since_ms", since_ms)
print("disk_closed", len(ml._mega_closed))
print("suppress", ml.mega_closed_backfill_suppressed(), "ts", ml._mega_closed_suppress_ts())
print("open_book", len(ml._mega_positions))
for p in ml._mega_positions[:6]:
    print("  book", p.get("id"), p.get("symbol"), p.get("side"))

if mc and not mc.paper:
    ex = [e for e in (mc.exchange_positions() or []) if float(e.get("contracts") or 0) > 0]
    print("exchange_open", len(ex))
    for e in ex[:8]:
        print("  ex", e.get("coin"), e.get("side"), e.get("contracts"))
    for coin in ["ETH", "SOL", "XRP", "INJ", "BTC", "AVAX", "LINK"]:
        try:
            tr = mc.user_trades(coin, start_ms=since_ms, limit=120) or []
            closes = [t for t in tr if abs(float(t.get("realizedPnl") or 0)) > 1e-8]
            if closes:
                last = closes[-1]
                sym = f"{coin}USDT"
                side = "LONG" if str(last.get("side")).upper() == "SELL" else "SHORT"
                still = ml._position_still_open(sym, side)
                print(
                    f"  {coin} close_fills={len(closes)} rpnl={last.get('realizedPnl')} "
                    f"still_open={still}"
                )
        except Exception as exc:
            print(f"  {coin} err={exc}")

added = sync_missing_closes_from_exchange(force=True)
print("sync_added", added, "disk_after", len(ml._mega_closed))
ui = ml._build_mega_closed_for_ui(light=True)
print("ui_rows", len(ui))
