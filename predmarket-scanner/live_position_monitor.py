#!/usr/bin/env python3
"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🔴 LIVE POSITION MONITOR — Real-time Position Tracking
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Canlı pozisyon takibi - Her saniye güncellenir
Tüm position verileri satır satır görüntülenir

RUN: python live_position_monitor.py
"""

import requests
import time
import os
from datetime import datetime

API_URL = "http://localhost:9003/api/live"

def clear_screen():
    os.system('clear' if os.name != 'nt' else 'cls')

def format_pnl(value):
    """Format P&L with colors"""
    if value >= 0:
        return f"\033[92m+${value:.2f}\033[0m"  # Green
    else:
        return f"\033[91m${value:.2f}\033[0m"   # Red

def format_pct(value):
    """Format percentage with colors"""
    if value >= 0:
        return f"\033[92m+{value:.2f}%\033[0m"
    else:
        return f"\033[91m{value:.2f}%\033[0m"

def print_position_detail(pos, index):
    """Print detailed position info"""
    print(f"\n{'═'*100}")
    print(f"  POSITION #{pos['id']} — {pos['symbol']} {pos['side']} {pos['leverage']}×")
    print(f"{'═'*100}")
    
    print(f"\n  📊 PRICE INFO:")
    print(f"    Entry Price:     ${pos['entry_price']:.4f}")
    print(f"    Current Price:   ${pos['current_price']:.4f}")
    print(f"    Price Change:    {((pos['current_price'] - pos['entry_price']) / pos['entry_price'] * 100):+.2f}%")
    
    print(f"\n  💰 POSITION SIZE:")
    print(f"    Size:            {pos['size']:.4f} {pos['symbol'].replace('USDT', '')}")
    print(f"    Stake (Capital): ${pos['stake_usd']:.2f}")
    print(f"    Position Value:  ${pos.get('position_value', pos['size'] * pos['current_price']):.2f}")
    print(f"    Leverage:        {pos['leverage']}×")
    
    print(f"\n  💵 FEES:")
    print(f"    Entry Fee:       ${pos.get('entry_fee', 0):.2f}")
    print(f"    Running Cost:    ${pos.get('total_fees', pos.get('entry_fee', 0)):.2f}")
    
    print(f"\n  📈 PROFIT & LOSS:")
    print(f"    Unrealized P&L:  {format_pnl(pos['unrealized_pnl'])}")
    print(f"    P&L Percentage:  {format_pct(pos['pnl_pct'])}")
    print(f"    ROI on Stake:    {format_pct(pos['pnl_pct'])}")
    
    print(f"\n  🎯 TARGETS:")
    print(f"    Take Profit:     ${pos['tp_target']:.4f}  ({((pos['tp_target'] - pos['current_price']) / pos['current_price'] * 100):+.2f}% away)")
    print(f"    Stop Loss:       ${pos['sl_target']:.4f}  ({((pos['current_price'] - pos['sl_target']) / pos['current_price'] * 100):+.2f}% away)")
    
    print(f"\n  ⏱️  DURATION:")
    print(f"    Entry Time:      {pos['entry_time_str']}")
    duration_sec = time.time() - pos['entry_time']
    duration_min = duration_sec / 60
    print(f"    Duration:        {duration_min:.1f} minutes ({duration_sec:.0f} seconds)")
    
    print(f"\n  📉 PRICE HISTORY ({len(pos.get('price_history', []))} data points):")
    if pos.get('price_history'):
        recent = pos['price_history'][-5:]
        print(f"    Recent 5:        {', '.join([f'${p:.4f}' for p in recent])}")
        print(f"    Min:             ${min(pos['price_history']):.4f}")
        print(f"    Max:             ${max(pos['price_history']):.4f}")
        print(f"    Volatility:      {(max(pos['price_history']) - min(pos['price_history'])) / pos['entry_price'] * 100:.2f}%")

def print_summary(data):
    """Print account summary"""
    s = data['summary']
    
    print(f"\n{'━'*100}")
    print(f"  💼 ACCOUNT SUMMARY")
    print(f"{'━'*100}")
    print(f"  Starting Capital:   ${s['starting_capital']:.2f}")
    print(f"  Current Capital:    ${s['current_capital']:.2f}")
    print(f"  Total P&L:          {format_pnl(s['total_pnl'])}  {format_pct(s['total_pnl_pct'])}")
    print(f"  Realized P&L:       {format_pnl(s['realized_pnl'])}")
    print(f"  Unrealized P&L:     {format_pnl(s['unrealized_pnl'])}")
    print(f"  Open Positions:     {s['open_trades']}")
    print(f"  Closed Positions:   {s['closed_trades']}")
    print(f"  Win Rate:           {s['win_rate']:.1f}% ({s['win_count']}/{s['closed_trades']})")
    print(f"  Total Fees Paid:    ${s.get('total_fees', 0):.2f}")
    print(f"  Total Taxes:        ${s.get('total_taxes', 0):.2f}")

def monitor():
    """Main monitoring loop"""
    print("\n🔴 LIVE POSITION MONITOR")
    print("Press Ctrl+C to stop\n")
    
    update_count = 0
    
    try:
        while True:
            try:
                response = requests.get(API_URL, timeout=5)
                if response.status_code == 200:
                    data = response.json()
                    
                    clear_screen()
                    
                    print("╔" + "═"*98 + "╗")
                    print("║" + " "*30 + "🔴 ELITE PRO — LIVE POSITION MONITOR" + " "*32 + "║")
                    print("╚" + "═"*98 + "╝")
                    
                    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    print(f"\n  🕐 Last Update: {now} | Update #{update_count + 1} | Mode: {data.get('mode', 'N/A')}")
                    
                    # Summary
                    print_summary(data)
                    
                    # Open Positions
                    open_pos = data['positions']['open']
                    
                    if open_pos:
                        print(f"\n{'━'*100}")
                        print(f"  🔥 OPEN POSITIONS ({len(open_pos)} active)")
                        print(f"{'━'*100}")
                        
                        for idx, pos in enumerate(open_pos, 1):
                            print_position_detail(pos, idx)
                    else:
                        print(f"\n{'━'*100}")
                        print(f"  ⚪ No open positions")
                        print(f"{'━'*100}")
                    
                    # Recent Signals
                    signals = data.get('signals', [])
                    if signals:
                        print(f"\n{'━'*100}")
                        print(f"  📡 RECENT SIGNALS ({len(signals)})")
                        print(f"{'━'*100}")
                        for sig in signals[-5:]:
                            chg_color = "\033[92m" if sig['change'] > 0 else "\033[91m"
                            print(f"    [{sig['time']}] {sig['symbol']:10s} {sig['type']:5s} ${sig['price']:8.4f} {chg_color}{sig['change']:+6.2f}%\033[0m [{sig['strength']}]")
                    
                    print(f"\n{'━'*100}")
                    print(f"  Next update in 1 second... (Press Ctrl+C to stop)")
                    print(f"{'━'*100}\n")
                    
                    update_count += 1
                    
                else:
                    print(f"❌ Error: API returned status {response.status_code}")
                
            except requests.exceptions.RequestException as e:
                print(f"❌ Connection error: {e}")
                print("Retrying in 2 seconds...")
                time.sleep(2)
                continue
            
            time.sleep(1)
            
    except KeyboardInterrupt:
        print("\n\n✅ Monitor stopped by user")
        print(f"Total updates: {update_count}\n")

if __name__ == "__main__":
    monitor()
