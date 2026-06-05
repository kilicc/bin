#!/usr/bin/env bash
# Port rolleri: 9005 paper | 9006 MEGA paper sim | 9007 demo-fapi canlı emir
set -euo pipefail

PROJECT="${GCP_PROJECT:-project-5f8843cb-1905-4297-af4}"
ZONE="${GCP_ZONE:-asia-northeast1-a}"
INSTANCE="${GCP_INSTANCE:-elite-full-mainnet}"
REMOTE="/opt/binancex/predmarket-scanner"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

gcloud compute scp \
  "${ROOT}/binance_elite_pro_9005_mainnet.py" \
  "${ROOT}/binance_elite_pro_9006_mainnet.py" \
  "${INSTANCE}:${REMOTE}/" \
  --zone="${ZONE}" --project="${PROJECT}"

gcloud compute scp \
  "${ROOT}/scenarios/binance_elite_8300_9005_mainnet.env" \
  "${INSTANCE}:${REMOTE}/scenarios/binance_elite_8300_9005_mainnet.env" \
  --zone="${ZONE}" --project="${PROJECT}"

gcloud compute scp \
  "${ROOT}/scenarios/binance_elite_mega_9006_mainnet.env" \
  "${INSTANCE}:${REMOTE}/scenarios/binance_elite_mega_9006_mainnet.env" \
  --zone="${ZONE}" --project="${PROJECT}"

gcloud compute ssh "${INSTANCE}" --zone="${ZONE}" --project="${PROJECT}" --command="
set -e
cd ${REMOTE}
touch .gcp_mainnet
sudo chown -R pro:pro data logs .pids data/reports 2>/dev/null || true

echo '=== Bot restart (9005/9006 paper, 9007 demo-fapi live) ==='
sudo systemctl restart binance-elite-9005-mainnet binance-elite-9006-mainnet binance-elite-9007-mainnet
sleep 35

python3 <<'PY'
import json, urllib.request
for port in (9005, 9006, 9007):
    d = json.load(urllib.request.urlopen(f'http://127.0.0.1:{port}/api/connection/live', timeout=20))
    print(
        f'P{port} paper={d.get(\"api_paper\")} live_orders={d.get(\"live_orders\")} '
        f'label={d.get(\"api_label\")} opens={d.get(\"open_positions\")}'
    )
PY
systemctl is-active binance-elite-9005-mainnet binance-elite-9006-mainnet binance-elite-9007-mainnet
"

echo "gcp_fix_trading (port roles) tamam."
