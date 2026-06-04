#!/usr/bin/env bash
# 9006 — demo API uPnL + hızlı kapanış doğrulama + kapalı tablo
set -euo pipefail

PROJECT="${GCP_PROJECT:-project-5f8843cb-1905-4297-af4}"
ZONE="${GCP_ZONE:-asia-northeast1-a}"
INSTANCE="${GCP_INSTANCE:-elite-full-mainnet}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

for f in elite_trader/mega_live.py elite_trader/mega_close_sync.py elite_trader/exchange_fill_truth.py elite_trader/exchange_open_display.py panel/elite_v2/js/paper-dashboard.js scenarios/binance_elite_mega_9006_mainnet.env; do
  safe="${f//\//__}"
  gcloud compute scp "${ROOT}/${f}" "${INSTANCE}:/tmp/_${safe}" --zone="${ZONE}" --project="${PROJECT}"
done

gcloud compute ssh "${INSTANCE}" --zone="${ZONE}" --project="${PROJECT}" --command="
set -e
cd /opt/binancex/predmarket-scanner
sudo cp /tmp/_elite_trader__mega_live.py elite_trader/mega_live.py
sudo cp /tmp/_elite_trader__mega_close_sync.py elite_trader/mega_close_sync.py
sudo cp /tmp/_elite_trader__exchange_fill_truth.py elite_trader/exchange_fill_truth.py
sudo cp /tmp/_elite_trader__exchange_open_display.py elite_trader/exchange_open_display.py
sudo cp /tmp/_panel__elite_v2__js__paper-dashboard.js panel/elite_v2/js/paper-dashboard.js
sudo cp /tmp/_scenarios__binance_elite_mega_9006_mainnet.env scenarios/binance_elite_mega_9006_mainnet.env
sudo chown -R pro:pro elite_trader panel scenarios
grep -E 'MEGA_SPIKE_BYPASS|MEGA_PANEL_POS|MEGA_PANEL_EXCHANGE_ONLY' scenarios/binance_elite_mega_9006_mainnet.env | head -5
sudo systemctl restart binance-elite-9006-mainnet
sleep 20
systemctl is-active binance-elite-9006-mainnet
"

echo "gcp_9006_exchange_truth tamam."
