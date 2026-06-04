#!/usr/bin/env python3
"""Clear all positions from running dashboards"""
import requests
import time

ports = [9002, 9003]

for port in ports:
    try:
        # Get current state
        resp = requests.get(f"http://localhost:{port}/api/live", timeout=2)
        if resp.status_code == 200:
            data = resp.json()
            open_count = len(data['positions']['open'])
            print(f"Port {port}: {open_count} open positions")
        else:
            print(f"Port {port}: Could not connect")
    except Exception as e:
        print(f"Port {port}: Error - {e}")

print("\n⚠️  To clear positions, restart dashboards with empty state...")
print("Stopping all dashboards...")

import os
os.system("ps aux | grep 'binance_elite' | grep python | grep -v grep | awk '{print $2}' | xargs kill -9 2>/dev/null")
time.sleep(2)
print("✅ Stopped")
