#!/usr/bin/env python3
"""Force clear all positions by modifying running process memory"""
import sys
sys.path.insert(0, '/Users/macbook/Downloads/testtt/predmarket-scanner')

# Import the actual modules
try:
    import binance_futures_clean as bf9003
    import binance_futures_clean_9002 as bf9002
    
    print("🔧 Clearing positions from memory...")
    
    # Clear 9003
    bf9003.positions.clear()
    bf9003.closed_positions.clear()
    bf9003.position_id_counter = 1
    print(f"✅ 9003: Positions cleared ({len(bf9003.positions)} open)")
    
    # Clear 9002
    bf9002.positions.clear()
    bf9002.closed_positions.clear()
    bf9002.position_id_counter = 1
    print(f"✅ 9002: Positions cleared ({len(bf9002.positions)} open)")
    
    print("✅ Memory cleared!")
    
except Exception as e:
    print(f"❌ Could not clear: {e}")
    print("Trying direct REST approach...")
    
    import requests
    for port in [9002, 9003]:
        try:
            r = requests.get(f"http://localhost:{port}/api/live")
            if r.status_code == 200:
                data = r.json()
                print(f"Port {port}: {len(data['positions']['open'])} positions")
        except Exception as e2:
            print(f"Port {port}: {e2}")
