#!/bin/bash
# 8210 - 8200 ile BİREBİR ayar (formül cache'siz temiz başlangıç)
cd "$(dirname "$0")"

# 8200 ayarlarını yükle
source scenarios/elite_apex_2x_24h.env

# 8210 için override
export PAPER_DB_PATH="data/elite_apex_2x_24h_8210.db"
export ELITE_SCAN_STATS_PATH="data/scan_stats_elite_apex_2x_24h_8210.json"
export DASHBOARD_PORT=8210

# Force yeni formül araştırması (cache bypass)
export ELITE_FORMULA_REFRESH_HOURS=0

echo "🔧 8210 Scanner - 8200 ile BİREBİR Ayar"
echo "   DB: $PAPER_DB_PATH"
echo "   Stats: $ELITE_SCAN_STATS_PATH"
echo "   Min Stake: $ELITE_MIN_STAKE_USD USD"
echo "   Max Stake: $ELITE_MAX_STAKE_USD USD (0=sınırsız)"
echo "   Max Open: $ELITE_MAX_OPEN"
echo "   Active Capital: $ELITE_ACTIVE_CAPITAL_PCT"
echo "   TP Target: $ELITE_TP_STAKE_PCT"
echo ""

nohup python3 -m elite_trader.scanner > logs/elite_apex_8210_scanner.log 2>&1 &
SCANNER_PID=$!
echo $SCANNER_PID > pids/elite_apex_8210_scanner.pid
echo "✅ Scanner başlatıldı (PID: $SCANNER_PID)"
echo "   URL: http://127.0.0.1:8210"
