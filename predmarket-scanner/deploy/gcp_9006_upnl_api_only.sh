#!/usr/bin/env bash
# uPnL yalnızca Binance API — panel + mega_live
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VM="${GCP_VM:-elite-full-mainnet}"
ZONE="${GCP_ZONE:-asia-northeast1-a}"
PROJECT="${GCP_PROJECT:-project-5f8843cb-1905-4297-af4}"
REMOTE="/opt/binancex/predmarket-scanner"

gcloud compute scp \
  "${ROOT}/elite_trader/mega_live.py" \
  "${ROOT}/panel/elite_v2/js/paper-dashboard.js" \
  "${ROOT}/panel/elite_v2/paper.html" \
  "${VM}:/tmp/" \
  --zone="${ZONE}" --project="${PROJECT}"

gcloud compute ssh "${VM}" --zone="${ZONE}" --project="${PROJECT}" --command="
set -e
sudo cp -f /tmp/mega_live.py ${REMOTE}/elite_trader/mega_live.py
sudo cp -f /tmp/paper-dashboard.js ${REMOTE}/panel/elite_v2/js/paper-dashboard.js
sudo cp -f /tmp/paper.html ${REMOTE}/panel/elite_v2/paper.html
sudo systemctl restart binance-elite-9006-mainnet
sleep 4
systemctl is-active binance-elite-9006-mainnet
curl -sf -m 15 -u x:x369 'http://127.0.0.1:9086/api/paper/mega/snapshot?light=1' | python3 -c \"
import sys,json
d=json.load(sys.stdin)
for p in (d.get('open') or [])[:3]:
  print(p.get('symbol'), 'upnl', p.get('exchange_unrealized_pnl'), 'missing', p.get('upnl_missing'))
\"
echo OK
"
