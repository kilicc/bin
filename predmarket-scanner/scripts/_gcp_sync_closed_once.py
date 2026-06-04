#!/usr/bin/env python3
"""One-shot: Binance userTrades -> mega_live_closed.json (9006)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

env_path = ROOT / "scenarios" / "binance_elite_mega_9006_mainnet.env"
if env_path.is_file():
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

from elite_trader.mega_close_sync import sync_missing_closes_from_exchange
from elite_trader.mega_live import (
    _build_mega_closed_for_ui,
    _ensure_mega_closed_loaded,
    _mega_closed,
    reconcile_mega_closed_with_exchange,
)

added = sync_missing_closes_from_exchange(force=True)
rep = reconcile_mega_closed_with_exchange(force=True)
_ensure_mega_closed_loaded()
ui = _build_mega_closed_for_ui(light=True)
print("sync_added", added)
print("reconcile", rep)
print("disk_rows", len(_mega_closed))
print("ui_rows", len(ui))
for row in ui[:8]:
    print(
        row.get("symbol"),
        row.get("side"),
        row.get("exit_reason"),
        row.get("final_pnl"),
    )
