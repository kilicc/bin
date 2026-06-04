#!/usr/bin/env python3
"""
Binance Futures Elite Pro — port 9005 (Elite APEX 8300 Plan B + demo canlı emir).
Çalıştır: python3 binance_elite_pro_9005.py
Panel: http://localhost:9005
"""
from __future__ import annotations

import os
import runpy
from pathlib import Path

_ROOT = Path(__file__).resolve().parent

try:
    from binance_futures_trader.network_ssl import apply_cert_env

    apply_cert_env()
except ImportError:
    try:
        import certifi

        os.environ.setdefault("SSL_CERT_FILE", certifi.where())
        os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())
    except ImportError:
        pass

os.environ["BINANCE_ELITE_PORT"] = "9005"
os.environ["BINANCE_ELITE_SCENARIO"] = str(
    _ROOT / "scenarios" / "binance_elite_8300_9005.env"
)
os.environ["BINANCE_LIVE_ORDERS"] = "1"
os.environ["BINANCE_FUTURES_DEMO"] = "1"
os.environ["BINANCE_FUTURES_TESTNET"] = "1"
os.environ["BN_FUT_MODE"] = "testnet"
os.environ["STARTING_BALANCE"] = "5000"
os.environ.setdefault("AGGRESSIVE_HIGH_GROWTH", "1")
os.environ.setdefault("BINANCE_FULL_UNIVERSE", "1")
os.environ.setdefault("BINANCE_SCAN_ALL_PERPETUALS", "1")
os.environ.setdefault("ELITE_STALE_TP_ENABLED", "0")

if __name__ == "__main__":
    runpy.run_path(str(_ROOT / "binance_elite_pro.py"), run_name="__main__")
