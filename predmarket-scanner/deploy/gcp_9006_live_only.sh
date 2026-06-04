#!/usr/bin/env bash
# 9005/9007 durdur → 9006 demo-fapi canlı (tek desk)
# Kullanım:
#   export MEGA9006_API_KEY='...'
#   export MEGA9006_API_SECRET='...'
#   bash deploy/gcp_9006_live_only.sh
set -euo pipefail

PROJECT="${GCP_PROJECT:-project-5f8843cb-1905-4297-af4}"
ZONE="${GCP_ZONE:-asia-northeast1-a}"
INSTANCE="${GCP_INSTANCE:-elite-full-mainnet}"
REMOTE="/opt/binancex/predmarket-scanner"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

KEY="${MEGA9006_API_KEY:-${MEGA_BINANCE_API_KEY:-}}"
SECRET="${MEGA9006_API_SECRET:-${MEGA_BINANCE_API_SECRET:-}}"
if [[ -z "${KEY}" || -z "${SECRET}" ]]; then
  if [[ -f "${ROOT}/scenarios/.env.mega_9006" ]]; then
    # shellcheck disable=SC1091
    source "${ROOT}/scenarios/.env.mega_9006"
    KEY="${MEGA_BINANCE_API_KEY:-${MEGA_9006_BINANCE_API_KEY:-}}"
    SECRET="${MEGA_BINANCE_API_SECRET:-${MEGA_9006_BINANCE_API_SECRET:-}}"
  fi
fi
if [[ -z "${KEY}" || -z "${SECRET}" ]]; then
  echo "MEGA9006_API_KEY ve MEGA9006_API_SECRET gerekli (veya scenarios/.env.mega_9006)" >&2
  exit 1
fi

for f in \
  binance_elite_pro.py \
  binance_elite_pro_9006_mainnet.py \
  elite_trader/mega_live.py \
  elite_trader/binance_data_hub.py \
  elite_trader/pipeline_alerts.py \
  elite_trader/network_guard.py \
  elite_trader/connection_alerts.py \
  elite_trader/binance_rest_budget.py \
  scenarios/binance_elite_mega_9006_mainnet.env; do
  gcloud compute scp "${ROOT}/${f}" "${INSTANCE}:/tmp/_$(basename "${f}")" \
    --zone="${ZONE}" --project="${PROJECT}"
done

gcloud compute ssh "${INSTANCE}" --zone="${ZONE}" --project="${PROJECT}" --command="
set -e
cd ${REMOTE}
sudo cp /tmp/_binance_elite_pro.py binance_elite_pro.py
sudo cp /tmp/_binance_elite_pro_9006_mainnet.py binance_elite_pro_9006_mainnet.py
sudo cp /tmp/_mega_live.py elite_trader/mega_live.py
sudo cp /tmp/_binance_data_hub.py elite_trader/binance_data_hub.py
sudo cp /tmp/_pipeline_alerts.py elite_trader/pipeline_alerts.py
sudo cp /tmp/_network_guard.py elite_trader/network_guard.py
sudo cp /tmp/_connection_alerts.py elite_trader/connection_alerts.py
sudo cp /tmp/_binance_rest_budget.py elite_trader/binance_rest_budget.py
sudo cp /tmp/_binance_elite_mega_9006_mainnet.env scenarios/binance_elite_mega_9006_mainnet.env
sudo install -m 600 /dev/null scenarios/.env.mega_9006
sudo tee scenarios/.env.mega_9006 >/dev/null <<ENV
MEGA_BINANCE_API_KEY=${KEY}
MEGA_BINANCE_API_SECRET=${SECRET}
MEGA_9006_BINANCE_API_KEY=${KEY}
MEGA_9006_BINANCE_API_SECRET=${SECRET}
STARTING_BALANCE=5000
ELITE_SESSION_START_FROM_ENV=1
MEGA_LIVE_ORDERS=1
MEGA_SIM_ENABLED=0
ENV
sudo chown pro:pro scenarios/.env.mega_9006 2>/dev/null || true

echo '=== 9005/9007 durdur (supervisor dahil) ==='
sudo systemctl stop binance-elite-9005-mainnet binance-elite-9007-mainnet elite-full-supervisor elite-9005-supervisor 2>/dev/null || true
sudo systemctl disable binance-elite-9005-mainnet binance-elite-9007-mainnet elite-full-supervisor 2>/dev/null || true

mkdir -p data/mega_9006
python3 <<'PY'
import json
from pathlib import Path
p = Path('data/mega_9006/mega_live_session.json')
sess = {}
if p.is_file():
    try:
        sess = json.loads(p.read_text())
    except Exception:
        pass
sess['wallet_anchor'] = 5000.0
sess['starting_balance'] = 5000.0
p.write_text(json.dumps(sess, indent=2) + '\\n')
print('session anchor', sess.get('wallet_anchor'))
PY

echo '=== 9006 demo-fapi canlı restart ==='
sudo systemctl enable binance-elite-9006-mainnet
sudo systemctl restart binance-elite-9006-mainnet
sleep 45
python3 <<'PY'
import json, urllib.request
for path in ('/api/connection/live', '/api/connection/alerts', '/api/status'):
    try:
        d = json.load(urllib.request.urlopen('http://127.0.0.1:9006'+path, timeout=35))
        if path.endswith('live'):
            print('live api_ok', d.get('api_ok'), 'paper', d.get('api_paper'), 'label', d.get('api_label'))
        elif path.endswith('alerts'):
            print('alerts', d.get('severity'), len(d.get('alerts') or []))
        else:
            print('status live_orders', d.get('live_orders'), 'mode', d.get('execution_mode'))
    except Exception as e:
        print(path, 'ERR', e)
PY
systemctl is-active binance-elite-9006-mainnet
systemctl is-active binance-elite-9005-mainnet 2>/dev/null || echo '9005 stopped'
systemctl is-active binance-elite-9007-mainnet 2>/dev/null || echo '9007 stopped'
"

echo "gcp_9006_live_only tamam."
