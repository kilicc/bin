#!/usr/bin/env bash
# 9006 — panel: API uPnL + ROI $ sütunları, bağlantı pill iyileştirmesi
set -euo pipefail

PROJECT="${GCP_PROJECT:-project-5f8843cb-1905-4297-af4}"
ZONE="${GCP_ZONE:-asia-northeast1-a}"
INSTANCE="${GCP_INSTANCE:-elite-full-mainnet}"
REMOTE="/opt/binancex/predmarket-scanner"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

FILES=(
  elite_trader/exchange_position_sync.py
  elite_trader/exchange_trade_truth.py
  elite_trader/mega_live.py
  scenarios/binance_elite_mega_9006_mainnet.env
  panel/elite_v2/paper.html
  panel/elite_v2/js/paper-dashboard.js
)
# cache bust panel: paper.html v=20260606g

for f in "${FILES[@]}"; do
  safe="${f//\//__}"
  gcloud compute scp "${ROOT}/${f}" "${INSTANCE}:/tmp/_${safe}" \
    --zone="${ZONE}" --project="${PROJECT}"
done

gcloud compute ssh "${INSTANCE}" --zone="${ZONE}" --project="${PROJECT}" --command="
set -e
cd ${REMOTE}
sudo cp /tmp/_elite_trader__exchange_position_sync.py elite_trader/exchange_position_sync.py
sudo cp /tmp/_elite_trader__exchange_trade_truth.py elite_trader/exchange_trade_truth.py
sudo cp /tmp/_elite_trader__mega_live.py elite_trader/mega_live.py
sudo cp /tmp/_scenarios__binance_elite_mega_9006_mainnet.env scenarios/binance_elite_mega_9006_mainnet.env
sudo cp /tmp/_panel__elite_v2__paper.html panel/elite_v2/paper.html
sudo cp /tmp/_panel__elite_v2__js__paper-dashboard.js panel/elite_v2/js/paper-dashboard.js
sudo chown -R pro:pro elite_trader panel scenarios 2>/dev/null || true
sudo systemctl restart binance-elite-9006-mainnet
sleep 28
systemctl is-active binance-elite-9006-mainnet
curl -sf -m 25 -u x:x369 'http://127.0.0.1:9006/api/paper/mega/snapshot?light=1' | python3 -c \"import json,sys;d=json.load(sys.stdin);print('closed',len(d.get('closed')or[]),d.get('closed_meta'))\"
sudo -u pro python3 scripts/reconcile_mega_closed_exchange.py 2>/dev/null | tail -2 || true
"

echo "gcp_9006_panel_upnl_roi_cols tamam — panel: Ctrl+Shift+R (v=20260606e)"
