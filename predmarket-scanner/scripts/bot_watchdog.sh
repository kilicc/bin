#!/bin/bash
# Bot Watchdog - API bağlantısı kopunca uyarı verir
# Kullanim: ./scripts/bot_watchdog.sh

LOG_FILE="logs/bot_watchdog.log"
API_URL="http://localhost:9005/api/live"
CHECK_INTERVAL=10  # 10 saniyede bir kontrol

echo "========================================" | tee -a "$LOG_FILE"
echo "BOT WATCHDOG BAŞLATILDI" | tee -a "$LOG_FILE"
echo "$(date '+%Y-%m-%d %H:%M:%S')" | tee -a "$LOG_FILE"
echo "========================================" | tee -a "$LOG_FILE"

consecutive_failures=0

while true; do
    timestamp=$(date '+%H:%M:%S')
    
    # API kontrolü
    response=$(curl -s --max-time 3 "$API_URL" 2>/dev/null)
    
    if [ $? -eq 0 ]; then
        # JSON'dan api_connected kontrolü
        api_connected=$(echo "$response" | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('api_connected',False))" 2>/dev/null)
        
        if [ "$api_connected" = "True" ]; then
            consecutive_failures=0
            echo "[$timestamp] ✅ API: BAĞLI" | tee -a "$LOG_FILE"
        else
            consecutive_failures=$((consecutive_failures + 1))
            echo "[$timestamp] ❌ API: KOPUK (Failure #$consecutive_failures)" | tee -a "$LOG_FILE"
            
            # 3 kere üst üste hata
            if [ $consecutive_failures -ge 3 ]; then
                echo "" | tee -a "$LOG_FILE"
                echo "========================================" | tee -a "$LOG_FILE"
                echo "🚨 KRITIK UYARI!" | tee -a "$LOG_FILE"
                echo "API BAĞLANTISI 3 KERE KOPTU!" | tee -a "$LOG_FILE"
                echo "$(date '+%Y-%m-%d %H:%M:%S')" | tee -a "$LOG_FILE"
                echo "========================================" | tee -a "$LOG_FILE"
                echo "" | tee -a "$LOG_FILE"
                
                # macOS notification (opsiyonel)
                osascript -e 'display notification "API bağlantısı koptu!" with title "Binance Elite Bot" sound name "Basso"' 2>/dev/null || true
            fi
        fi
    else
        consecutive_failures=$((consecutive_failures + 1))
        echo "[$timestamp] ❌ BOT API YANIT VERMIYOR (Failure #$consecutive_failures)" | tee -a "$LOG_FILE"
        
        if [ $consecutive_failures -ge 3 ]; then
            echo "" | tee -a "$LOG_FILE"
            echo "========================================" | tee -a "$LOG_FILE"
            echo "🚨 KRITIK: BOT ÇALIŞMIYOR!" | tee -a "$LOG_FILE"
            echo "$(date '+%Y-%m-%d %H:%M:%S')" | tee -a "$LOG_FILE"
            echo "========================================" | tee -a "$LOG_FILE"
            echo "" | tee -a "$LOG_FILE"
            
            osascript -e 'display notification "Bot çalışmıyor!" with title "Binance Elite Bot" sound name "Basso"' 2>/dev/null || true
        fi
    fi
    
    sleep $CHECK_INTERVAL
done
