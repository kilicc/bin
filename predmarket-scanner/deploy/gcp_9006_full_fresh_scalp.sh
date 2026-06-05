#!/usr/bin/env bash
# 9006 — tam sıfır (flatten + arşiv) + $30–40 hızlı net TP ayarları
set -euo pipefail

PROJECT="${GCP_PROJECT:-project-5f8843cb-1905-4297-af4}"
ZONE="${GCP_ZONE:-asia-northeast1-a}"
INSTANCE="${GCP_INSTANCE:-elite-full-mainnet}"
REMOTE="/opt/binancex/predmarket-scanner"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REASON="${1:-user_full_fresh_scalp_30_40_net_tp}"

for f in elite_trader/mega_live.py elite_trader/mega_close_sync.py elite_trader/exchange_fill_truth.py scenarios/binance_elite_mega_9006_mainnet.env scripts/reset_mega_9006_fresh.py; do
  safe="${f//\//__}"
  gcloud compute scp "${ROOT}/${f}" "${INSTANCE}:/tmp/_${safe}" --zone="${ZONE}" --project="${PROJECT}"
done

gcloud compute ssh "${INSTANCE}" --zone="${ZONE}" --project="${PROJECT}" --command="
set -e
cd ${REMOTE}
sudo cp /tmp/_elite_trader__mega_live.py elite_trader/mega_live.py
sudo cp /tmp/_elite_trader__mega_close_sync.py elite_trader/mega_close_sync.py
sudo cp /tmp/_elite_trader__exchange_fill_truth.py elite_trader/exchange_fill_truth.py
sudo cp /tmp/_scenarios__binance_elite_mega_9006_mainnet.env scenarios/binance_elite_mega_9006_mainnet.env
sudo cp /tmp/_scripts__reset_mega_9006_fresh.py scripts/reset_mega_9006_fresh.py
sudo chown -R pro:pro elite_trader scenarios scripts
grep -E '^MEGA_DEMO_FAST|^MEGA_MIN_CLOSE|^MEGA_TP_STAKE|^MEGA_BOOT_OBSERVE_SEC' scenarios/binance_elite_mega_9006_mainnet.env
export BINANCE_ELITE_PORT=9006 MEGA_INSTANCE_ID=9006
.venv/bin/python scripts/reset_mega_9006_fresh.py --reason '${REASON}' --capital 5000 --yes
sudo systemctl restart binance-elite-9006-mainnet
sleep 35
systemctl is-active binance-elite-9006-mainnet
curl -sf -u x:x369 http://127.0.0.1:9086/api/paper/mega/snapshot?light=1 | python3 -c \"
import sys,json
d=json.load(sys.stdin)
print('open',len(d.get('open')or[]),'closed',len(d.get('closed')or[]))
print('anchor',(d.get('summary')or{}).get('session_anchor'))
print('boot',(d.get('scan')or{}).get('boot_observe'))
\"
"

echo "gcp_9006_full_fresh_scalp tamam."
