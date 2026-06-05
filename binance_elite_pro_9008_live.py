#!/usr/bin/env python3
"""
Binance Futures Elite Pro — port 9008 (MEGA LIVE - Gerçek Emirler).
Panel: http://34.146.107.66:9086 (nginx proxy)
Endpoint: https://demo-fapi.binance.com
Cüzdan: $5000 | Stake: $1000 | Leverage: 10x
"""
from __future__ import annotations

import os
import runpy
from pathlib import Path

_ROOT = Path(__file__).resolve().parent

# SSL/TLS Setup
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

# Port ve Instance ID
os.environ["BINANCE_ELITE_PORT"] = "9008"
os.environ["MEGA_INSTANCE_ID"] = "9008"
os.environ["BINANCE_ELITE_SCENARIO"] = str(_ROOT / "scenarios" / "binance_elite_mega_9008_live.env")

# YENİ API KEYS (demo-fapi.binance.com)
os.environ["MEGA_BINANCE_API_KEY"] = "zWr9KBbdGKKBrHMDICrEXEZ20B5kzfN775A6ISMb8bgU8ifxTKYLkXTVO3D3ORWv"
os.environ["MEGA_BINANCE_API_SECRET"] = "GL9WxVYBjRaIcuODbTBAAYxqCmZnR7xBRVj49rnzKViO2bP9jFORIA7JTATL19Mr"
os.environ["BINANCE_API_KEY"] = "zWr9KBbdGKKBrHMDICrEXEZ20B5kzfN775A6ISMb8bgU8ifxTKYLkXTVO3D3ORWv"
os.environ["BINANCE_API_SECRET"] = "GL9WxVYBjRaIcuODbTBAAYxqCmZnR7xBRVj49rnzKViO2bP9jFORIA7JTATL19Mr"

# Instance-specific keys
os.environ["MEGA_9008_BINANCE_API_KEY"] = "zWr9KBbdGKKBrHMDICrEXEZ20B5kzfN775A6ISMb8bgU8ifxTKYLkXTVO3D3ORWv"
os.environ["MEGA_9008_BINANCE_API_SECRET"] = "GL9WxVYBjRaIcuODbTBAAYxqCmZnR7xBRVj49rnzKViO2bP9jFORIA7JTATL19Mr"

# CANLI EMİRLER (demo-fapi.binance.com)
os.environ["MEGA_LIVE_ORDERS"] = "1"
os.environ["MEGA_SIM_ENABLED"] = "0"
os.environ["ELITE_PAPER_PARALLEL"] = "0"
os.environ["ELITE_LIVE_ONLY"] = "1"
os.environ["BINANCE_FUTURES_DEMO"] = "1"
os.environ["BINANCE_FUTURES_TESTNET"] = "1"
os.environ["BN_FUT_MODE"] = "testnet"
os.environ["MEGA_BN_FUT_MODE"] = "testnet"
os.environ["MEGA_BINANCE_FUTURES_DEMO"] = "1"
os.environ["ELITE_BINANCE_REST_ENABLED"] = "1"
os.environ["ELITE_BINANCE_DATA_HUB"] = "0"
os.environ["MEGA_ASYNC_HUB"] = "1"
os.environ["BN_FUT_MARK_WS"] = "1"
os.environ["BN_FUT_FAST_WS"] = "1"
os.environ["STARTING_BALANCE"] = "5000"
os.environ["ELITE_SESSION_START_FROM_ENV"] = "1"

# DOĞRU ENDPOINT (EN ÖNEMLİ!)
os.environ["BINANCE_FUTURES_REST_BASE"] = "https://demo-fapi.binance.com"
os.environ["MEGA_BINANCE_FUTURES_REST_BASE"] = "https://demo-fapi.binance.com"
os.environ["MEGA_9008_BINANCE_FUTURES_REST_BASE"] = "https://demo-fapi.binance.com"

# Stake ve Leverage — hızlı scalp
os.environ["ELITE_POSITION_SIZE_USD"] = "400"
os.environ["ELITE_LEVERAGE"] = "10"
os.environ["ELITE_DEFAULT_LEVERAGE"] = "10"
os.environ["MEGA_LEVERAGE"] = "10"
os.environ["MEGA_FIXED_STAKE_USD"] = "400"
os.environ["MEGA_FLASH_REVERSAL_STAKE_MIN_USD"] = "200"
os.environ["MEGA_FLASH_REVERSAL_STAKE_MAX_USD"] = "500"
os.environ["MEGA_FLASH_REVERSAL_LEVERAGE"] = "10"
os.environ["ELITE_TP_STAKE_PCT"] = "0.0035"
os.environ["ELITE_TP_TRIGGER_FRAC"] = "0.82"
os.environ["ELITE_EXIT_TP_ONLY"] = "1"
os.environ["BERSERK2_FLASH_REVERSAL_ENABLED"] = "1"
os.environ["BERSERK2_FLASH_EARLY_ENTRY"] = "1"
os.environ["MEGA_FLASH_LONG_BLOCK_IN_BEAR"] = "0"
os.environ["MEGA_BEAR_BLOCK_LONG"] = "0"
os.environ["MEGA_SYSTEM_SCORE_FLASH_BYPASS"] = "1"
os.environ["MEGA_BOOT_OBSERVE"] = "0"
os.environ["MEGA_BOOT_OBSERVE_SEC"] = "0"
os.environ["BINANCE_LIVE_ORDERS"] = "0"
os.environ["ELITE_BINANCE_API_EXCLUSIVE"] = "9008"
os.environ["MEGA_RATE_LIMIT_SAFE"] = "1"
os.environ["ELITE_EXCHANGE_POLL_IV_MS"] = "60000"

# Diğer ayarlar
os.environ.setdefault("ELITE_BIND_HOST", "127.0.0.1")
os.environ.setdefault("BINANCE_RECV_WINDOW", "15000")
os.environ.setdefault("ELITE_CONNECTION_KEEPALIVE_SEC", "90")
os.environ.setdefault("ELITE_DEMO_API_RECONNECT_SEC", "8")
os.environ.setdefault("MEGA_API_RECONNECT_SEC", "8")

if __name__ == "__main__":
    runpy.run_path(str(_ROOT / "binance_elite_pro.py"), run_name="__main__")
