#!/usr/bin/env bash
# 9006 — API keepalive + panel kopuk gösterimi (—)
set -euo pipefail

PROJECT="${GCP_PROJECT:-project-5f8843cb-1905-4297-af4}"
ZONE="${GCP_ZONE:-asia-northeast1-a}"
INSTANCE="${GCP_INSTANCE:-elite-full-mainnet}"
REMOTE="/opt/binancex/predmarket-scanner"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

FILES=(
  binance_elite_pro.py
  elite_trader/connection_alerts.py
  elite_trader/mega_live.py
  panel/elite_v2/js/paper-dashboard.js
  panel/elite_v2/paper.html
  scenarios/binance_elite_mega_9006_mainnet.env
)

for f in "${FILES[@]}"; do
  safe="${f//\//__}"
  gcloud compute scp "${ROOT}/${f}" "${INSTANCE}:/tmp/_${safe}" \
    --zone="${ZONE}" --project="${PROJECT}"
done

gcloud compute ssh "${INSTANCE}" --zone="${ZONE}" --project="${PROJECT}" --command="
set -e
cd ${REMOTE}
sudo cp /tmp/_binance_elite_pro.py binance_elite_pro.py
sudo cp /tmp/_elite_trader__connection_alerts.py elite_trader/connection_alerts.py
sudo cp /tmp/_elite_trader__mega_live.py elite_trader/mega_live.py
sudo cp /tmp/_panel__elite_v2__js__paper-dashboard.js panel/elite_v2/js/paper-dashboard.js
sudo cp /tmp/_panel__elite_v2__paper.html panel/elite_v2/paper.html
sudo cp /tmp/_scenarios__binance_elite_mega_9006_mainnet.env scenarios/binance_elite_mega_9006_mainnet.env
sudo chown -R pro:pro binance_elite_pro.py elite_trader panel scenarios 2>/dev/null || true
grep -E '^ELITE_API_STALE|^ELITE_CONNECTION_KEEPALIVE' scenarios/binance_elite_mega_9006_mainnet.env
sudo systemctl restart binance-elite-9006-mainnet
sleep 30
systemctl is-active binance-elite-9006-mainnet
"

echo "gcp_9006_api_conn_ui tamam."
