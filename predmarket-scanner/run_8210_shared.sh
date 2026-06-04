#!/bin/bash
cd "$(dirname "$0")"
export PAPER_DB_PATH="data/elite_apex_2x_24h.db"
export DASHBOARD_PORT=8210
nohup python3 dashboard.py > logs/elite_apex_8210_shared.log 2>&1 &
echo $! > pids/dashboard_8210_shared.pid
echo "✅ Port 8210 başlatıldı (8200'ün DB'sini kullanıyor)"
echo "   DB: $PAPER_DB_PATH"
echo "   URL: http://127.0.0.1:8210"
