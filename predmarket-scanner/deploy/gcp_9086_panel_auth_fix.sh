#!/usr/bin/env bash
# Panel 9086: panel-assets auth kaldır + paper.html overlay failsafe
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VM="${GCP_VM:-elite-full-mainnet}"
ZONE="${GCP_ZONE:-asia-northeast1-a}"
PROJECT="${GCP_PROJECT:-project-5f8843cb-1905-4297-af4}"
REMOTE="/opt/binancex/predmarket-scanner"

gcloud compute scp \
  "${ROOT}/deploy/nginx-elite-full-ports.conf" \
  "${ROOT}/panel/elite_v2/paper.html" \
  "${VM}:/tmp/" \
  --zone="${ZONE}" --project="${PROJECT}"

gcloud compute ssh "${VM}" --zone="${ZONE}" --project="${PROJECT}" --command="
set -e
sudo cp -f /tmp/nginx-elite-full-ports.conf /etc/nginx/sites-available/elite-full-ports
sudo cp -f /tmp/paper.html ${REMOTE}/panel/elite_v2/paper.html
sudo nginx -t
sudo systemctl reload nginx
echo OK: nginx panel-assets auth off + paper.html failsafe
curl -sf -m 3 -w 'assets_noauth:%{http_code}\n' http://127.0.0.1:9086/panel-assets/css/paper.css -o /dev/null
curl -sf -m 8 -u x:x369 -w 'paper:%{http_code}\n' http://127.0.0.1:9086/paper -o /dev/null
"
