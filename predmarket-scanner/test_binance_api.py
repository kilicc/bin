#!/usr/bin/env python3
"""Test Binance Futures API connection"""
import os
from dotenv import load_dotenv
from binance_futures_trader.client import BinanceFuturesClient

load_dotenv()

print("🔍 Testing Binance Futures API Connection...")
print(f"API Key: {os.getenv('BINANCE_FUTURES_API_KEY', 'NOT SET')[:20]}...")
print(f"Secret: {os.getenv('BINANCE_FUTURES_API_SECRET', 'NOT SET')[:20]}...")

client = BinanceFuturesClient()

print(f"\n📊 Client Mode: {'PAPER' if client.paper else 'LIVE'}")

# Test 1: Fetch BTCUSDT price
print("\n🔹 Test 1: Fetch BTCUSDT klines...")
try:
    klines = client.klines_history('BTCUSDT', '1m', days=1)
    if klines and len(klines) > 0:
        price = float(klines[-1][4])
        print(f"✅ Success! BTCUSDT Price: ${price:,.2f}")
    else:
        print("❌ No klines data returned")
except Exception as e:
    print(f"❌ Error: {e}")

# Test 2: Fetch account balance
print("\n🔹 Test 2: Fetch account balance...")
try:
    balance = client.balance()
    print(f"✅ Success! Balance data:")
    for asset, amount in balance.items():
        if amount > 0:
            print(f"   {asset}: {amount:,.2f}")
except Exception as e:
    print(f"❌ Error: {e}")

# Test 3: Fetch open positions
print("\n🔹 Test 3: Fetch open positions...")
try:
    positions = client.positions()
    print(f"✅ Success! Found {len(positions)} positions")
    for pos in positions[:3]:
        print(f"   {pos}")
except Exception as e:
    print(f"❌ Error: {e}")

print("\n✨ Test complete!")
