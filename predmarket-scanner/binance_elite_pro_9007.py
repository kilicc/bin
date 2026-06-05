#!/usr/bin/env python3
"""
Binance Futures Elite Pro — port 9007 (MEGA canlı desk, ayrı API hesabı).
Çalıştır: python3 binance_elite_pro_9007.py
Panel: http://localhost:9007/paper
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

os.environ["BINANCE_ELITE_PORT"] = "9007"
os.environ["MEGA_INSTANCE_ID"] = "9007"
os.environ["BINANCE_ELITE_SCENARIO"] = str(
    _ROOT / "scenarios" / "binance_elite_mega_9007.env"
)
os.environ["BINANCE_LIVE_ORDERS"] = "0"
os.environ["MEGA_LIVE_ORDERS"] = "1"
os.environ["MEGA_SIM_ENABLED"] = "0"
os.environ["BINANCE_FUTURES_DEMO"] = "1"
os.environ["BINANCE_FUTURES_TESTNET"] = "1"
os.environ["BN_FUT_MODE"] = "testnet"
os.environ.setdefault("BINANCE_RECV_WINDOW", "15000")
os.environ.setdefault("AGGRESSIVE_HIGH_GROWTH", "1")
os.environ.setdefault("BINANCE_FULL_UNIVERSE", "0")
os.environ.setdefault("BINANCE_SCAN_ALL_PERPETUALS", "0")
os.environ.setdefault("ELITE_STALE_TP_ENABLED", "0")

if __name__ == "__main__":
    runpy.run_path(str(_ROOT / "binance_elite_pro.py"), run_name="__main__")
