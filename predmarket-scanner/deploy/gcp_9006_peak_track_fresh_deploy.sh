#!/usr/bin/env bash
# 9006 — peak-track hub deploy + stop + flatten/wipe + 2dk bekle + start
set -euo pipefail

PROJECT="${GCP_PROJECT:-project-5f8843cb-1905-4297-af4}"
ZONE="${GCP_ZONE:-asia-northeast1-a}"
INSTANCE="${GCP_INSTANCE:-elite-full-mainnet}"
REMOTE="/opt/binancex/predmarket-scanner"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REASON="${1:-user_peak_track_hub_fresh_deploy}"
WAIT_SEC="${2:-120}"

FILES=(
  elite_trader/mega_live.py
  elite_trader/mega_close_sync.py
  elite_trader/exchange_fill_truth.py
  elite_trader/mega_control.py
  scenarios/binance_elite_mega_9006_mainnet.env
  scripts/reset_mega_9006_fresh.py
  docs/MEGA_SYSTEM_BOT_CHECKPOINT.md
)

echo "=== SCP (${#FILES[@]} dosya) → ${INSTANCE} ==="
for f in "${FILES[@]}"; do
  safe="${f//\//__}"
  gcloud compute scp "${ROOT}/${f}" "${INSTANCE}:/tmp/_${safe}" \
    --zone="${ZONE}" --project="${PROJECT}"
done

gcloud compute ssh "${INSTANCE}" --zone="${ZONE}" --project="${PROJECT}" --command="
set -e
cd ${REMOTE}
echo '=== stop 9006 ==='
sudo systemctl stop binance-elite-9006-mainnet || true
sleep 3
for i in \$(seq 1 15); do
  if ! curl -sf --max-time 2 http://127.0.0.1:9006/api/heartbeat >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

echo '=== deploy files ==='
sudo cp /tmp/_elite_trader__mega_live.py elite_trader/mega_live.py
sudo cp /tmp/_elite_trader__mega_close_sync.py elite_trader/mega_close_sync.py
sudo cp /tmp/_elite_trader__exchange_fill_truth.py elite_trader/exchange_fill_truth.py
sudo cp /tmp/_elite_trader__mega_control.py elite_trader/mega_control.py
sudo cp /tmp/_scenarios__binance_elite_mega_9006_mainnet.env scenarios/binance_elite_mega_9006_mainnet.env
sudo cp /tmp/_scripts__reset_mega_9006_fresh.py scripts/reset_mega_9006_fresh.py
sudo cp /tmp/_docs__MEGA_SYSTEM_BOT_CHECKPOINT.md docs/MEGA_SYSTEM_BOT_CHECKPOINT.md 2>/dev/null || true
sudo chown -R pro:pro elite_trader scenarios scripts docs 2>/dev/null || true
grep -E '^MEGA_PEAK_TRACK|^MEGA_PANEL_EXCHANGE' scenarios/binance_elite_mega_9006_mainnet.env || true

echo '=== flatten + wipe mega_9006 ==='
export BINANCE_ELITE_PORT=9006 MEGA_INSTANCE_ID=9006
.venv/bin/python scripts/reset_mega_9006_fresh.py --reason '${REASON}' --capital 5000 --yes

echo \"=== bekle ${WAIT_SEC}s ===\"
sleep ${WAIT_SEC}

echo '=== start 9006 ==='
sudo systemctl start binance-elite-9006-mainnet
sleep 40
systemctl is-active binance-elite-9006-mainnet
curl -sf -u x:x369 'http://127.0.0.1:9086/api/paper/mega/snapshot?light=1' | python3 -c \"
import sys, json
d = json.load(sys.stdin)
s = d.get('summary') or {}
print('open', len(d.get('open') or []), 'closed', len(d.get('closed') or []))
print('control', (d.get('control') or {}).get('state'))
print('anchor', s.get('session_anchor') or s.get('starting_balance'))
\"
"

echo "gcp_9006_peak_track_fresh_deploy tamam."
