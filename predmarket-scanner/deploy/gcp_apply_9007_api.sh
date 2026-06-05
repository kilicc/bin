#!/usr/bin/env bash
# 9007 API — yalnızca demo-fapi.binance.com (demo.binance.com key)
set -euo pipefail

PROJECT="${GCP_PROJECT:-project-5f8843cb-1905-4297-af4}"
ZONE="${GCP_ZONE:-asia-northeast1-a}"
INSTANCE="${GCP_INSTANCE:-elite-full-mainnet}"
REMOTE="/opt/binancex/predmarket-scanner"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="${ROOT}/.env"

if [[ ! -f "${ENV_FILE}" ]]; then
  echo ".env bulunamadı: ${ENV_FILE}" >&2
  exit 1
fi

get_env() {
  local key="$1"
  grep -E "^${key}=" "${ENV_FILE}" | tail -1 | cut -d= -f2- | tr -d '\r' || true
}

KEY=$(get_env "MEGA_9007_BINANCE_API_KEY")
SECRET=$(get_env "MEGA_9007_BINANCE_API_SECRET")

if [[ -z "${KEY}" || -z "${SECRET}" ]]; then
  echo "MEGA_9007_BINANCE_API_KEY ve MEGA_9007_BINANCE_API_SECRET .env içinde dolu olmalı" >&2
  exit 1
fi

if [[ "${#KEY}" -lt 32 ]]; then
  echo "MEGA_9007_BINANCE_API_KEY geçersiz (çok kısa)" >&2
  exit 1
fi

echo "=== 9007 demo-fapi sunucuya uygulanıyor (key: ${KEY:0:8}…) ==="

gcloud compute scp "${ENV_FILE}" "${INSTANCE}:/tmp/pms_env_9007" \
  --zone="${ZONE}" --project="${PROJECT}"

gcloud compute scp "${ROOT}/binance_elite_pro_9007_mainnet.py" "${INSTANCE}:${REMOTE}/binance_elite_pro_9007_mainnet.py" \
  --zone="${ZONE}" --project="${PROJECT}"

gcloud compute scp "${ROOT}/scenarios/binance_elite_mega_9007_mainnet.env" "${INSTANCE}:${REMOTE}/scenarios/binance_elite_mega_9007_mainnet.env" \
  --zone="${ZONE}" --project="${PROJECT}"

gcloud compute ssh "${INSTANCE}" --zone="${ZONE}" --project="${PROJECT}" --command="
set -e
cd ${REMOTE}
patch_env() {
  local k=\$1 v=\$2
  if grep -q \"^\${k}=\" .env 2>/dev/null; then
    sed -i \"s|^\${k}=.*|\${k}=\${v}|\" .env
  else
    echo \"\${k}=\${v}\" >> .env
  fi
}
while IFS= read -r line; do
  [[ \"\${line}\" =~ ^MEGA_9007_ ]] || continue
  k=\${line%%=*}
  v=\${line#*=}
  patch_env \"\${k}\" \"\${v}\"
done < /tmp/pms_env_9007
# 9007 — yalnızca demo-fapi
patch_env MEGA_LIVE_ORDERS 1
patch_env MEGA_SIM_ENABLED 0
patch_env MEGA_BINANCE_FUTURES_DEMO 1
patch_env MEGA_BINANCE_FUTURES_TESTNET 1
patch_env MEGA_BN_FUT_MODE testnet
patch_env MEGA_9007_BINANCE_FUTURES_DEMO 1
patch_env MEGA_9007_BINANCE_FUTURES_TESTNET 1
patch_env MEGA_9007_BN_FUT_MODE testnet
patch_env ELITE_PUBLIC_MAINNET_FALLBACK 0
# Global BINANCE_* dokunma — 9005/9006 paper portları .env'den etkilenmesin
rm -f /tmp/pms_env_9007

sudo systemctl restart binance-elite-9007-mainnet
sleep 30

cd ${REMOTE} && source .venv/bin/activate
python3 <<'PY'
import json, os, urllib.request
from dotenv import load_dotenv
load_dotenv('.env')
load_dotenv('scenarios/binance_elite_mega_9007_mainnet.env', override=True)
os.environ['MEGA_INSTANCE_ID']='9007'
os.environ['BINANCE_ELITE_PORT']='9007'
for k,v in (
    ('BINANCE_FUTURES_DEMO','1'),('BINANCE_FUTURES_TESTNET','1'),('BN_FUT_MODE','testnet'),
    ('MEGA_BINANCE_FUTURES_DEMO','1'),('MEGA_BINANCE_FUTURES_TESTNET','1'),('MEGA_BN_FUT_MODE','testnet'),
):
    os.environ[k]=v
key = os.getenv('MEGA_9007_BINANCE_API_KEY','')
print('key_prefix:', key[:8]+'...' if key else 'MISSING')
print('BN_FUT_MODE:', os.getenv('BN_FUT_MODE'), 'DEMO:', os.getenv('BINANCE_FUTURES_DEMO'))
from binance_futures_trader.client import BinanceFuturesClient
c = BinanceFuturesClient(
    api_key=key,
    api_secret=os.getenv('MEGA_9007_BINANCE_API_SECRET'),
    testnet=True,
    futures_demo=True,
    mode='testnet')
print('paper:', c.paper, 'base:', c._api_base(), 'auth:', (c._auth_error or '')[:80])
try:
    bal = c._get('/fapi/v2/balance', signed=True)
    usdt = next((x for x in bal if x.get('asset')=='USDT'), {})
    print('REST OK avail=', usdt.get('availableBalance'), 'wallet=', usdt.get('balance'))
except Exception as e:
    print('REST FAIL:', str(e)[:180])
try:
    live = json.load(urllib.request.urlopen('http://127.0.0.1:9007/api/connection/live', timeout=15))
    print('panel label=', live.get('api_label'), 'paper=', live.get('api_paper'), 'api_ok=', live.get('api_ok'))
    if 'demo-fapi' not in str(live.get('api_label') or ''):
        raise SystemExit('9007 mainnet label — demo-fapi bekleniyor')
except Exception as e:
    print('panel check skip (servis henüz hazır değil):', str(e)[:120])
PY
systemctl is-active binance-elite-9007-mainnet
grep -E 'MEGA canlı|demo-fapi|demo' ${REMOTE}/logs/binance_elite_mega_9007_mainnet.log | tail -3
"

echo "gcp_apply_9007_api tamam (demo-fapi only)."
