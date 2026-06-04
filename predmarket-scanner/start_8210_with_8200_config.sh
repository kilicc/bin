#!/bin/bash
cd "$(dirname "$0")"

# 8210 kendi DB'si
export PAPER_DB_PATH="data/elite_apex_2x_24h_8210.db"
export ELITE_SCAN_STATS_PATH="data/scan_stats_elite_apex_2x_24h_8210.json"

# 8200 ile AYNI ayarlar
source scenarios/elite_apex_2x_24h.env

# 8210 için override
export PAPER_DB_PATH="data/elite_apex_2x_24h_8210.db"
export ELITE_SCAN_STATS_PATH="data/scan_stats_elite_apex_2x_24h_8210.json"

echo "🔧 8210 Scanner - 8200 Ayarlarıyla"
echo "   DB: $PAPER_DB_PATH"
echo "   Min Stake: $ELITE_MIN_STAKE_USD"
echo "   Max Stake: $ELITE_MAX_STAKE_USD"
echo "   Mode: APEX 2x24h (8200 ile aynı)"

nohup python3 -m elite_trader.scanner > logs/elite_apex_8210_scanner.log 2>&1 &
echo $!
echo "✅ 8210 başlatıldı (8200 ile aynı ayarlar)"
