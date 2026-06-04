#!/bin/bash
# Quick Position Check (single snapshot)

curl -s "http://localhost:9005/api/live" | python3 << 'EOF'
import sys, json

data = json.load(sys.stdin)
positions = data.get('positions', {}).get('open', [])

print("╔════════════════════════════════════════════════════════════════════════════╗")
print("║                        POSITION SNAPSHOT                                  ║")
print("╚════════════════════════════════════════════════════════════════════════════╝")
print()
print(f"Balance: ${data.get('balance', 0):.2f}")
print(f"Open: {len(positions)} positions")
print()

if positions:
    for i, p in enumerate(positions, 1):
        print(f"#{i} {p.get('symbol')} {p.get('side')} @ ${p.get('entry_price'):.4f}")
        print(f"   Current: ${p.get('current_price', 0):.4f} | uPnL: ${p.get('unrealized_pnl', 0):+.2f} | ROE: {p.get('roe_pct', 0):+.2f}%")
        print()
else:
    print("No open positions")
    print()
EOF
