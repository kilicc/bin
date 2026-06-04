#!/usr/bin/env bash
# Panel 9086: cache bust, inline snapshot bootstrap, nginx cache headers
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VM="${GCP_VM:-elite-full-mainnet}"
ZONE="${GCP_ZONE:-asia-northeast1-a}"
PROJECT="${GCP_PROJECT:-project-5f8843cb-1905-4297-af4}"
REMOTE="/opt/binancex/predmarket-scanner"

gcloud compute scp \
  "${ROOT}/deploy/nginx-elite-full-ports.conf" \
  "${ROOT}/panel/elite_v2/paper.html" \
  "${ROOT}/panel/elite_v2/css/paper.css" \
  "${ROOT}/panel/elite_v2/js/paper-dashboard.js" \
  "${ROOT}/panel/elite_v2/js/connection-banner.js" \
  "${VM}:/tmp/" \
  --zone="${ZONE}" --project="${PROJECT}"

gcloud compute ssh "${VM}" --zone="${ZONE}" --project="${PROJECT}" --command="
set -e
sudo cp -f /tmp/nginx-elite-full-ports.conf /etc/nginx/sites-available/elite-full-ports
sudo cp -f /tmp/paper.html ${REMOTE}/panel/elite_v2/paper.html
sudo cp -f /tmp/paper.css ${REMOTE}/panel/elite_v2/css/paper.css
sudo cp -f /tmp/paper-dashboard.js ${REMOTE}/panel/elite_v2/js/paper-dashboard.js
sudo cp -f /tmp/connection-banner.js ${REMOTE}/panel/elite_v2/js/connection-banner.js
sudo nginx -t && sudo systemctl reload nginx
echo OK panel deploy
curl -sf -m 3 -w 'css:%{http_code}\n' http://127.0.0.1:9086/panel-assets/css/paper.css -o /dev/null
curl -sf -m 12 -u x:x369 -w 'snap:%{http_code}\n' 'http://127.0.0.1:9086/api/paper/mega/snapshot?light=1' -o /dev/null
grep -c '20260604' ${REMOTE}/panel/elite_v2/paper.html
"
