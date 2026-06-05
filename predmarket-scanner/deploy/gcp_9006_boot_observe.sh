#!/usr/bin/env bash
# MEGA 9006 — 5 dk boot gözlem + scalp env + panel + sıfırlama
set -euo pipefail

PROJECT="${GCP_PROJECT:-project-5f8843cb-1905-4297-af4}"
ZONE="${GCP_ZONE:-asia-northeast1-a}"
INSTANCE="${GCP_INSTANCE:-elite-full-mainnet}"
REMOTE="/opt/binancex/predmarket-scanner"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REASON="${1:-boot_observe_deploy_$(date -u +%Y%m%d)}"

FILES=(
  elite_trader/mega_boot_observe.py
  elite_trader/mega_control.py
  elite_trader/mega_live.py
  elite_trader/mega_market_regime.py
  elite_trader/mega_close_sync.py
  elite_trader/exchange_settlement.py
  elite_trader/mode_engines/mega_scoring.py
  elite_trader/mode_reject_buffer.py
  panel/elite_v2/js/paper-dashboard.js
  scripts/reset_mega_9006_fresh.py
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
sudo cp /tmp/_elite_trader__mega_boot_observe.py elite_trader/mega_boot_observe.py
sudo cp /tmp/_elite_trader__mega_control.py elite_trader/mega_control.py
sudo cp /tmp/_elite_trader__mega_live.py elite_trader/mega_live.py
sudo cp /tmp/_elite_trader__mega_market_regime.py elite_trader/mega_market_regime.py
sudo cp /tmp/_elite_trader__mega_close_sync.py elite_trader/mega_close_sync.py
sudo cp /tmp/_elite_trader__exchange_settlement.py elite_trader/exchange_settlement.py
sudo cp /tmp/_elite_trader__mode_engines__mega_scoring.py elite_trader/mode_engines/mega_scoring.py
sudo cp /tmp/_elite_trader__mode_reject_buffer.py elite_trader/mode_reject_buffer.py
sudo cp /tmp/_panel__elite_v2__js__paper-dashboard.js panel/elite_v2/js/paper-dashboard.js
sudo cp /tmp/_scripts__reset_mega_9006_fresh.py scripts/reset_mega_9006_fresh.py
sudo cp /tmp/_scenarios__binance_elite_mega_9006_mainnet.env scenarios/binance_elite_mega_9006_mainnet.env
sudo chown -R pro:pro elite_trader panel scripts scenarios 2>/dev/null || true
chmod +x scripts/reset_mega_9006_fresh.py
export BINANCE_ELITE_PORT=9006 MEGA_INSTANCE_ID=9006
.venv/bin/python scripts/reset_mega_9006_fresh.py --reason '${REASON}' --yes
grep -E '^MEGA_BOOT_OBSERVE' scenarios/binance_elite_mega_9006_mainnet.env
echo '=== restart 9006 ==='
sudo systemctl restart binance-elite-9006-mainnet
sleep 40
systemctl is-active binance-elite-9006-mainnet
curl -sf http://127.0.0.1:9086/api/paper/mode_snapshot?mode=mega | python3 -c \"
import sys,json
d=json.load(sys.stdin)
s=d.get('scan') or {}
b=s.get('boot_observe') or {}
print('boot_observe', b)
print('entry_block', (s.get('entry_block_reason') or '')[:80])
\"
"

echo "gcp_9006_boot_observe tamam."
