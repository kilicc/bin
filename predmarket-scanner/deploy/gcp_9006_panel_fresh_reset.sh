#!/usr/bin/env bash
# MEGA 9006 — panel positionRisk gecikme düzeltmesi + tam oturum sıfırlama (borsa flatten)
set -euo pipefail

PROJECT="${GCP_PROJECT:-project-5f8843cb-1905-4297-af4}"
ZONE="${GCP_ZONE:-asia-northeast1-a}"
INSTANCE="${GCP_INSTANCE:-elite-full-mainnet}"
REMOTE="/opt/binancex/predmarket-scanner"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REASON="${1:-user_panel_stale_upnl_full_reset}"

FILES=(
  elite_trader/mega_live.py
  elite_trader/mega_close_sync.py
  panel/elite_v2/js/paper-dashboard.js
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
sudo cp /tmp/_elite_trader__mega_live.py elite_trader/mega_live.py
sudo cp /tmp/_elite_trader__mega_close_sync.py elite_trader/mega_close_sync.py
sudo cp /tmp/_panel__elite_v2__js__paper-dashboard.js panel/elite_v2/js/paper-dashboard.js
sudo cp /tmp/_scenarios__binance_elite_mega_9006_mainnet.env scenarios/binance_elite_mega_9006_mainnet.env
sudo chown -R pro:pro elite_trader panel scenarios 2>/dev/null || true
grep -E '^MEGA_PANEL_REST_PRIORITY|^MEGA_PANEL_POS_RISK' scenarios/binance_elite_mega_9006_mainnet.env
export BINANCE_ELITE_PORT=9006 MEGA_INSTANCE_ID=9006
.venv/bin/python scripts/reset_mega_9006_fresh.py --reason '${REASON}' --yes
echo '=== restart 9006 ==='
sudo systemctl restart binance-elite-9006-mainnet
sleep 40
systemctl is-active binance-elite-9006-mainnet
curl -sf http://127.0.0.1:9086/api/paper/mega/ticks | python3 -c \"
import sys,json
d=json.load(sys.stdin)
for p in (d.get('open') or [])[:3]:
  print(p.get('symbol'), 'uPnL', (p.get('exchange_display') or {}).get('unRealizedProfit'), 'age_ms', p.get('exchange_data_age_ms'))
\"
"

echo "gcp_9006_panel_fresh_reset tamam."
