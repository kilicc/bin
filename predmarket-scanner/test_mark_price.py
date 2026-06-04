#!/usr/bin/env python3
"""Test mark_price API"""
import os
from dotenv import load_dotenv

# Force reload env
load_dotenv(override=True)

# Set MODE before importing client
os.environ['BN_FUT_MODE'] = 'testnet'
os.environ['BINANCE_FUTURES_TESTNET'] = '1'

from binance_futures_trader.client import BinanceFuturesClient

print(f"🔍 ENV CHECK:")
print(f"MODE: {os.getenv('BN_FUT_MODE', 'NOT SET')}")
print(f"TESTNET: {os.getenv('BINANCE_FUTURES_TESTNET', 'NOT SET')}")
print(f"API Key: {os.getenv('BINANCE_FUTURES_API_KEY', 'NOT SET')[:20]}...")

client = BinanceFuturesClient()
print(f"\n📊 Client Mode: {'PAPER' if client.paper else 'TESTNET'}")

# Test mark_price
print("\n🔹 Test: Fetch BTC mark price...")
try:
    price = client.mark_price('BTC')
    if price:
        print(f"✅ Success! BTC Price: ${price:,.2f}")
    else:
        print("❌ No price returned")
except Exception as e:
    print(f"❌ Error: {e}")

print("\n🔹 Test: Fetch ETH mark price...")
try:
    price = client.mark_price('ETH')
    if price:
        print(f"✅ Success! ETH Price: ${price:,.2f}")
    else:
        print("❌ No price returned")
except Exception as e:
    print(f"❌ Error: {e}")
