#!/bin/bash
# Real-Time Position & P&L Monitor (Sub-second updates)

BOT_API="http://localhost:9005/api/live"
UPDATE_INTERVAL=0.5  # 500ms update

# Terminal control
clear
tput civis  # Hide cursor

# Cleanup on exit
trap 'tput cnorm; clear; exit' INT TERM

echo "╔════════════════════════════════════════════════════════════════════════════╗"
echo "║             REAL-TIME POSITION MONITOR (500ms update)                     ║"
echo "╚════════════════════════════════════════════════════════════════════════════╝"
echo ""

while true; do
    TIMESTAMP=$(date '+%H:%M:%S.%3N')
    
    # Move cursor to top (keep header)
    tput cup 3 0
    
    # Fetch data
    RESPONSE=$(curl -s --max-time 1 "$BOT_API" 2>/dev/null)
    
    if [ $? -eq 0 ]; then
        # Parse with Python
        python3 << 'PYEOF'
import sys, json
from datetime import datetime

try:
    data = json.loads('''RESPONSE'''.replace("'''", '"""'))
    
    positions = data.get('positions', {}).get('open', [])
    summary = data.get('summary', {})
    
    print(f"⏰ Last Update: TIMESTAMP")
    print(f"💰 Balance: ${data.get('balance', 0):.2f} | Total P&L: ${summary.get('total_pnl', 0):.2f}")
    print(f"📊 Open Positions: {len(positions)}/{summary.get('max_open', 0)}")
    print("─" * 78)
    print()
    
    if positions:
        # Header
        print(f"{'SYMBOL':<12} {'SIDE':<6} {'ENTRY':<10} {'CURRENT':<10} {'uPNL':<12} {'ROE%':<8} {'AGE':<8}")
        print("─" * 78)
        
        for p in positions[:10]:  # Max 10 positions
            symbol = p.get('symbol', 'N/A')[:12]
            side = p.get('side', 'N/A')
            entry = p.get('entry_price', 0)
            current = p.get('current_price', 0)
            upnl = p.get('unrealized_pnl', 0)
            roe = p.get('roe_pct', 0)
            age_sec = p.get('duration_sec', 0)
            
            # Color code P&L
            if upnl > 0:
                pnl_str = f"🟢 ${upnl:+.2f}"
            elif upnl < 0:
                pnl_str = f"🔴 ${upnl:+.2f}"
            else:
                pnl_str = f"⚪ ${upnl:+.2f}"
            
            # Format age
            if age_sec < 60:
                age = f"{age_sec:.0f}s"
            elif age_sec < 3600:
                age = f"{age_sec/60:.1f}m"
            else:
                age = f"{age_sec/3600:.1f}h"
            
            print(f"{symbol:<12} {side:<6} ${entry:<9.4f} ${current:<9.4f} {pnl_str:<20} {roe:>6.2f}% {age:>7}")
    else:
        print()
        print("                    No open positions")
        print()
    
    # Add 5 blank lines to clear old data
    for _ in range(5):
        print(" " * 78)
        
except Exception as e:
    print(f"Parse error: {e}")
    for _ in range(15):
        print(" " * 78)
PYEOF
    else
        echo "API connection failed..."
        sleep 2
    fi
    
    sleep $UPDATE_INTERVAL
done
