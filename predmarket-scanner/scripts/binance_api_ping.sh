#!/bin/bash
# Binance Demo API Direct Ping Test

API_KEY="EbPW0xmkNtTEdCtjgyMWCckXpFgnthi5TzTxHHabwDEbPX2ya7kL5aRRTGyMQjP4"
BINANCE_URL="https://demo-fapi.binance.com/fapi/v1/ping"

echo "╔════════════════════════════════════════════════════════╗"
echo "║       BINANCE DEMO API DIRECT PING TEST               ║"
echo "╚════════════════════════════════════════════════════════╝"
echo ""

for i in {1..5}; do
    START=$(date +%s%N)
    RESPONSE=$(curl -s -w "\n%{http_code}" --max-time 2 "$BINANCE_URL" -H "X-MBX-APIKEY: $API_KEY" 2>/dev/null)
    END=$(date +%s%N)
    HTTP_CODE=$(echo "$RESPONSE" | tail -n1)
    LATENCY=$(echo "scale=1; ($END - $START) / 1000000" | bc)
    
    if [ "$HTTP_CODE" = "200" ]; then
        printf "Ping #%d: ✅ %6.1f ms\n" "$i" "$LATENCY"
    else
        printf "Ping #%d: ❌ FAILED (HTTP %s)\n" "$i" "$HTTP_CODE"
    fi
    sleep 1
done

echo ""
echo "Test tamamlandı!"
