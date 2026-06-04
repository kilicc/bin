"""Binance Futures WebSocket base URL selection."""
from __future__ import annotations

import os

from binance_futures_trader import config as cfg
from binance_futures_trader.client import api_base

MAIN_WS = "wss://fstream.binance.com"
TESTNET_WS = "wss://fstream.binancefuture.com"
DEMO_WS_PRIMARY = "wss://fstream.binance.com"
DEMO_WS_SECONDARY = "wss://fstream.binancefuture.com"


def _is_demo() -> bool:
    return bool(
        os.getenv("BINANCE_FUTURES_DEMO", "").strip() in ("1", "true")
        or getattr(cfg, "FUTURES_DEMO", False)
        or api_base() == "https://demo-fapi.binance.com"
    )


def ws_market_base() -> str:
    if _is_demo():
        return DEMO_WS_PRIMARY
    if cfg.MODE == "testnet" or (cfg.TESTNET and cfg.API_KEY):
        return TESTNET_WS
    base = api_base()
    if base in ("https://testnet.binancefuture.com", "https://demo-fapi.binance.com"):
        return TESTNET_WS
    return MAIN_WS


def ws_user_base() -> str:
    return ws_market_base()
