#!/usr/bin/env python3
"""
Binance Futures Elite Pro — port 9004 (agresif $22k senaryosu).
Çalıştır: python3 binance_elite_pro_9004.py
Açılış: http://localhost:9004
"""
from __future__ import annotations

import os
import runpy
from pathlib import Path

_ROOT = Path(__file__).resolve().parent

os.environ.setdefault("BINANCE_ELITE_PORT", "9004")
os.environ.setdefault(
    "BINANCE_ELITE_SCENARIO",
    str(_ROOT / "scenarios" / "aggressive_9004.env"),
)
os.environ.setdefault("BINANCE_FULL_UNIVERSE", "1")
os.environ.setdefault("AGGRESSIVE_HIGH_GROWTH", "1")

if __name__ == "__main__":
    runpy.run_path(str(_ROOT / "binance_elite_pro.py"), run_name="__main__")
