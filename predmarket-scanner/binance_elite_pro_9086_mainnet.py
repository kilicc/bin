#!/usr/bin/env python3
"""
Binance Futures Elite Pro — port 9086 (MEGA İlk Cloud Import Konfigürasyonu).
Panel: http://34.146.107.66:9086
API anahtarları: scenarios/.env.mega_9086 (git dışı, chmod 600)
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

os.environ["BINANCE_ELITE_PORT"] = "9086"
os.environ["MEGA_INSTANCE_ID"] = "9086"
os.environ["BINANCE_ELITE_SCENARIO"] = str(
    _ROOT / "scenarios" / "binance_elite_mega_9086_mainnet.env"
)

_secrets = _ROOT / "scenarios" / ".env.mega_9086"
if _secrets.is_file():
    try:
        from dotenv import load_dotenv

        load_dotenv(_secrets, override=True)
    except ImportError:
        pass

_telegram = _ROOT / "scenarios" / ".env.telegram_9086"
if _telegram.is_file():
    try:
        from dotenv import load_dotenv

        load_dotenv(_telegram, override=True)
    except ImportError:
        pass

# Varsayılan: demo-fapi canlı (senaryo + .env.mega_9086 ile override)
_live = os.getenv("MEGA_LIVE_ORDERS", "1").strip().lower() in ("1", "true", "yes")
if _live:
    os.environ["MEGA_LIVE_ORDERS"] = "1"
    os.environ["MEGA_SIM_ENABLED"] = "0"
    os.environ["BINANCE_FUTURES_DEMO"] = "1"
    os.environ["BINANCE_FUTURES_TESTNET"] = "1"
    os.environ["BN_FUT_MODE"] = "testnet"
    os.environ["MEGA_BN_FUT_MODE"] = "testnet"
    os.environ["MEGA_BINANCE_FUTURES_DEMO"] = "1"
    os.environ["ELITE_LIVE_ONLY"] = "1"
    os.environ["ELITE_PAPER_PARALLEL"] = "0"
    os.environ["ELITE_BINANCE_REST_ENABLED"] = "1"
    os.environ["ELITE_BINANCE_DATA_HUB"] = "0"
    os.environ["MEGA_ASYNC_HUB"] = "1"
    os.environ["BN_FUT_MARK_WS"] = "1"
    os.environ["BN_FUT_FAST_WS"] = "1"
    os.environ["STARTING_BALANCE"] = os.getenv("STARTING_BALANCE", "5000")
    os.environ["ELITE_SESSION_START_FROM_ENV"] = "1"
else:
    os.environ["MEGA_LIVE_ORDERS"] = "0"
    os.environ["MEGA_SIM_ENABLED"] = "1"
    os.environ["BINANCE_FUTURES_DEMO"] = "0"
    os.environ["BN_FUT_MODE"] = "paper"
    os.environ["ELITE_LIVE_ONLY"] = "0"
    os.environ["ELITE_PAPER_PARALLEL"] = "1"
    os.environ["ELITE_BINANCE_REST_ENABLED"] = "0"
    os.environ["ELITE_BINANCE_DATA_HUB"] = "1"
    os.environ["ELITE_BINANCE_HUB_URL"] = "http://127.0.0.1:9007"
    os.environ["MEGA_ASYNC_HUB"] = "0"
    os.environ["BN_FUT_MARK_WS"] = "0"
    os.environ["BN_FUT_FAST_WS"] = "0"

os.environ.setdefault("ELITE_BIND_HOST", "127.0.0.1")
os.environ.setdefault("BINANCE_RECV_WINDOW", "15000")
os.environ.setdefault("ELITE_CONNECTION_KEEPALIVE_SEC", "90")
os.environ.setdefault("ELITE_DEMO_API_RECONNECT_SEC", "8")
os.environ.setdefault("MEGA_API_RECONNECT_SEC", "8")

if __name__ == "__main__":
    runpy.run_path(str(_ROOT / "binance_elite_pro.py"), run_name="__main__")
