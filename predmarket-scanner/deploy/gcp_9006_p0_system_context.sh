#!/usr/bin/env bash
# MEGA 9006 — P0 system context (entry/exit snapshot + audit)
set -euo pipefail

PROJECT="${GCP_PROJECT:-project-5f8843cb-1905-4297-af4}"
ZONE="${GCP_ZONE:-asia-northeast1-a}"
INSTANCE="${GCP_INSTANCE:-elite-full-mainnet}"
REMOTE="/opt/binancex/predmarket-scanner"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

FILES=(
  elite_trader/mega_system_context.py
  elite_trader/mega_live.py
  scenarios/binance_elite_mega_9006_mainnet.env
)

for f in "${FILES[@]}"; do
  base="$(basename "${f}")"
  gcloud compute scp "${ROOT}/${f}" "${INSTANCE}:/tmp/_${base}" \
    --zone="${ZONE}" --project="${PROJECT}"
done

gcloud compute ssh "${INSTANCE}" --zone="${ZONE}" --project="${PROJECT}" --command="
set -e
cd ${REMOTE}
sudo cp /tmp/_mega_system_context.py elite_trader/mega_system_context.py
sudo cp /tmp/_mega_live.py elite_trader/mega_live.py
sudo cp /tmp/_binance_elite_mega_9006_mainnet.env scenarios/binance_elite_mega_9006_mainnet.env
sudo chown -R pro:pro elite_trader scenarios 2>/dev/null || true
grep -E '^MEGA_SYSTEM_CONTEXT' scenarios/binance_elite_mega_9006_mainnet.env || true
echo '=== restart 9006 ==='
sudo systemctl restart binance-elite-9006-mainnet
sleep 40
python3 <<'PY'
import json, urllib.request
for path in ('/api/status',):
    try:
        d = json.load(urllib.request.urlopen('http://127.0.0.1:9006'+path, timeout=30))
        print('status', 'live_orders', d.get('live_orders'), 'control', (d.get('mega_control') or {}).get('state'))
    except Exception as e:
        print(path, 'ERR', e)
PY
systemctl is-active binance-elite-9006-mainnet
"

echo "gcp_9006_p0_system_context tamam."
