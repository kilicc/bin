#!/usr/bin/env bash
# 9006 — MEGA hibrit checkpoint: kod+env+panel deploy, kapalı kayıt arşiv/sil, flatten, 5dk bekle, start
set -euo pipefail

PROJECT="${GCP_PROJECT:-project-5f8843cb-1905-4297-af4}"
ZONE="${GCP_ZONE:-asia-northeast1-a}"
INSTANCE="${GCP_INSTANCE:-elite-full-mainnet}"
REMOTE="/opt/binancex/predmarket-scanner"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REASON="${1:-mega_hybrid_checkpoint_20260606}"
WAIT_SEC="${2:-300}"
CAPITAL="${3:-5000}"

FILES=(
  elite_trader/mega_live.py
  elite_trader/mega_async_hub.py
  elite_trader/mega_close_sync.py
  elite_trader/exchange_fill_truth.py
  elite_trader/exchange_trade_truth.py
  elite_trader/exchange_position_sync.py
  elite_trader/mega_control.py
  scenarios/binance_elite_mega_9006_mainnet.env
  scripts/reset_mega_9006_fresh.py
  panel/elite_v2/paper.html
  panel/elite_v2/js/paper-dashboard.js
  docs/MEGA_9006_HYBRID_CHECKPOINT.md
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
for i in \$(seq 1 20); do
  if ! curl -sf --max-time 2 http://127.0.0.1:9006/api/heartbeat >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

echo '=== deploy files ==='
sudo cp /tmp/_elite_trader__mega_live.py elite_trader/mega_live.py
sudo cp /tmp/_elite_trader__mega_async_hub.py elite_trader/mega_async_hub.py
sudo cp /tmp/_elite_trader__mega_close_sync.py elite_trader/mega_close_sync.py
sudo cp /tmp/_elite_trader__exchange_fill_truth.py elite_trader/exchange_fill_truth.py
sudo cp /tmp/_elite_trader__exchange_trade_truth.py elite_trader/exchange_trade_truth.py
sudo cp /tmp/_elite_trader__exchange_position_sync.py elite_trader/exchange_position_sync.py
sudo cp /tmp/_elite_trader__mega_control.py elite_trader/mega_control.py
sudo cp /tmp/_scenarios__binance_elite_mega_9006_mainnet.env scenarios/binance_elite_mega_9006_mainnet.env
sudo cp /tmp/_scripts__reset_mega_9006_fresh.py scripts/reset_mega_9006_fresh.py
sudo cp /tmp/_panel__elite_v2__paper.html panel/elite_v2/paper.html
sudo cp /tmp/_panel__elite_v2__js__paper-dashboard.js panel/elite_v2/js/paper-dashboard.js
sudo cp /tmp/_docs__MEGA_9006_HYBRID_CHECKPOINT.md docs/MEGA_9006_HYBRID_CHECKPOINT.md 2>/dev/null || true
sudo chown -R pro:pro elite_trader panel scenarios scripts docs 2>/dev/null || true
grep -E '^MEGA_PANEL_CLOSED_VERIFIED|^MEGA_EXCHANGE_VELOCITY|^MEGA_CLOSED_REQUIRE' scenarios/binance_elite_mega_9006_mainnet.env | head -8

echo '=== fresh session (flatten + arşiv + kapalı sil) ==='
export BINANCE_ELITE_PORT=9006 MEGA_INSTANCE_ID=9006
.venv/bin/python scripts/reset_mega_9006_fresh.py --reason '${REASON}' --capital ${CAPITAL} --yes

echo \"=== bekle \${WAIT_SEC}s (5 dk) ===\"
sleep ${WAIT_SEC}

echo '=== start 9006 ==='
sudo systemctl start binance-elite-9006-mainnet
sleep 40
systemctl is-active binance-elite-9006-mainnet
curl -sf -u x:x369 'http://127.0.0.1:9086/api/paper/mega/snapshot?light=1' | python3 -c \"
import sys, json
d = json.load(sys.stdin)
print('open', len(d.get('open') or []), 'closed', len(d.get('closed') or []))
print('anchor', (d.get('summary') or {}).get('session_anchor'))
print('closed_meta', d.get('closed_meta'))
\"
"

echo "gcp_9006_hybrid_checkpoint_fresh tamam — panel: Ctrl+Shift+R (v=20260606j)"
