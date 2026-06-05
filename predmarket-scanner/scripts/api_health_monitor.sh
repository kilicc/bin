#!/bin/bash
# API Health & Speed Monitor - Real-time

LOG_FILE="logs/api_health.log"
BOT_API="http://localhost:9005/api/live"
CHECK_INTERVAL=5

echo "╔════════════════════════════════════════════════════════╗"
echo "║          API HEALTH & SPEED MONITOR                   ║"
echo "╚════════════════════════════════════════════════════════╝"
echo ""
echo "Checking every ${CHECK_INTERVAL}s... (Ctrl+C to stop)"
echo ""

while true; do
    TIMESTAMP=$(date '+%H:%M:%S')
    
    # Bot API Speed Test
    START=$(date +%s%N)
    RESPONSE=$(curl -s -w "\n%{http_code}" --max-time 3 "$BOT_API" 2>/dev/null)
    END=$(date +%s%N)
    HTTP_CODE=$(echo "$RESPONSE" | tail -n1)
    RESPONSE_TIME=$(echo "scale=3; ($END - $START) / 1000000" | bc)
    
    if [ "$HTTP_CODE" = "200" ]; then
        # Parse JSON
        API_CONNECTED=$(echo "$RESPONSE" | head -n-1 | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('api_connected', False))" 2>/dev/null)
        BALANCE=$(echo "$RESPONSE" | head -n-1 | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('balance', 0))" 2>/dev/null)
        OPEN_POS=$(echo "$RESPONSE" | head -n-1 | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d.get('positions',{}).get('open',[])))" 2>/dev/null)
        
        # Speed indicator
        if (( $(echo "$RESPONSE_TIME < 100" | bc -l) )); then
            SPEED="🟢 ULTRA FAST"
        elif (( $(echo "$RESPONSE_TIME < 300" | bc -l) )); then
            SPEED="🟡 FAST"
        elif (( $(echo "$RESPONSE_TIME < 1000" | bc -l) )); then
            SPEED="🟠 NORMAL"
        else
            SPEED="🔴 SLOW"
        fi
        
        printf "[%s] %s (%.0fms) | API: %s | Bal: \$%s | Pos: %s\n" \
            "$TIMESTAMP" "$SPEED" "$RESPONSE_TIME" "$API_CONNECTED" "$BALANCE" "$OPEN_POS"
    else
        echo "[${TIMESTAMP}] 🔴 BOT API DOWN (HTTP $HTTP_CODE)"
    fi
    
    sleep $CHECK_INTERVAL
done
