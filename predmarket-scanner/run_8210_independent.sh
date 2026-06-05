#!/bin/bash
# 8210 - Kendi DB'si, 8200'ün stats'ini kullan
cd "$(dirname "$0")"

# Kendi DB'si
export PAPER_DB_PATH="data/elite_apex_2x_24h_8210.db"
export DASHBOARD_PORT=8210

# 8200'ün stats dosyasını kullan (tarama sonuçları)
export ELITE_SHARED_STATS="data/scan_stats_elite_apex_2x_24h.json"

# Temiz başlat
rm -f "$PAPER_DB_PATH"
python3 -c "from pathlib import Path; from elite_trader.db import init_db; init_db(Path('$PAPER_DB_PATH')).close()"

echo "🆕 Port 8210 - Independent Mode"
echo "   Own DB: $PAPER_DB_PATH"
echo "   Shared Stats: $ELITE_SHARED_STATS (from 8200)"
echo "   URL: http://127.0.0.1:8210"

# Sadece dashboard (scanner yok)
nohup python3 dashboard.py > logs/elite_apex_8210_independent.log 2>&1 &
echo $!
