#!/usr/bin/env bash
# 9007 demo-fapi kontrol + kapalı/açık yerel kayıt sıfırla (9005/9006 dokunulmaz)
set -euo pipefail

PROJECT="${GCP_PROJECT:-project-5f8843cb-1905-4297-af4}"
ZONE="${GCP_ZONE:-asia-northeast1-a}"
INSTANCE="${GCP_INSTANCE:-elite-full-mainnet}"
REMOTE="/opt/binancex/predmarket-scanner"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REASON="${RESET_REASON:-user_reset_9007_demo_fresh}"

gcloud compute scp \
  "${ROOT}/scripts/reset_mega_9007_data.py" \
  "${INSTANCE}:${REMOTE}/scripts/" \
  --zone="${ZONE}" --project="${PROJECT}"

gcloud compute ssh "${INSTANCE}" --zone="${ZONE}" --project="${PROJECT}" --command="
set -e
cd ${REMOTE}

echo '=== Demo-fapi API (doğrudan) ==='
.venv/bin/python <<'PY'
import os, json
os.environ['BINANCE_ELITE_PORT']='9007'
os.environ['MEGA_INSTANCE_ID']='9007'
for line in open('scenarios/binance_elite_mega_9007_mainnet.env'):
    line=line.strip()
    if not line or line.startswith('#') or '=' not in line: continue
    k,v=line.split('=',1); os.environ[k.strip()]=v.strip()
for line in open('.env'):
    line=line.strip()
    if not line or line.startswith('#') or '=' not in line: continue
    k,v=line.split('=',1)
    if k.startswith('MEGA_9007_'): os.environ[k]=v.strip()
from binance_futures_trader.client import BinanceFuturesClient
from elite_trader.mega_live import mega_binance_env
key=mega_binance_env('BINANCE_API_KEY')
secret=mega_binance_env('BINANCE_API_SECRET') or mega_binance_env('BINANCE_FUTURES_API_SECRET')
mc=BinanceFuturesClient(api_key=key,api_secret=secret,testnet=True,futures_demo=True,mode='testnet')
mc.sync_server_time(force=True)
w=mc.exchange_wallet()
pos=[p for p in (mc.exchange_positions() or []) if abs(float(p.get('positionAmt') or p.get('contracts') or 0))>1e-8]
print('demo wallet', w.get('total_wallet_balance'), 'open', len(pos))
PY

echo ''
echo '=== Durdur 9007 ==='
sudo systemctl stop binance-elite-9007-mainnet

echo '=== 9007 veri sıfırla ==='
.venv/bin/python scripts/reset_mega_9007_data.py --yes --reason '${REASON}'

echo '=== Restart 9007 ==='
sudo systemctl restart binance-elite-9007-mainnet
sleep 25

curl -s http://127.0.0.1:9007/api/connection/live | python3 -c \"import json,sys;d=json.load(sys.stdin);print('conn api_ok',d.get('api_ok'),'auth',d.get('auth_error'),'label',d.get('api_label'))\"
curl -s http://127.0.0.1:9007/api/paper/mega/snapshot | python3 -c \"import json,sys;d=json.load(sys.stdin);s=d.get('summary')or{};print('snap open',len(d.get('open')or[]),'closed',len(d.get('closed')or[]),'equity',s.get('current_capital'),'anchor',s.get('session_anchor'))\"
systemctl is-active binance-elite-9007-mainnet
"

echo "gcp_reset_9007_data tamam."
