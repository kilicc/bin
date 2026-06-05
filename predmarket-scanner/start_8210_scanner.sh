#!/bin/bash
cd "$(dirname "$0")"
export PAPER_DB_PATH="data/elite_apex_2x_24h_8210.db"
export ELITE_SCAN_STATS_PATH="data/scan_stats_elite_apex_2x_24h_8210.json"

echo "🚀 8210 Scanner başlatılıyor..."
echo "   DB: $PAPER_DB_PATH"
echo "   Stats: $ELITE_SCAN_STATS_PATH"

nohup python3 -m elite_trader.scanner > logs/elite_apex_8210_scanner.log 2>&1 &
echo $!
echo "✅ Scanner başlatıldı (8200'den bağımsız tarama)"
