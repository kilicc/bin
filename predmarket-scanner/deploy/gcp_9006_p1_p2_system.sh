#!/usr/bin/env bash
# MEGA 9006 — P1 rapor + P2 system_score (kapı env ile)
set -euo pipefail

PROJECT="${GCP_PROJECT:-project-5f8843cb-1905-4297-af4}"
ZONE="${GCP_ZONE:-asia-northeast1-a}"
INSTANCE="${GCP_INSTANCE:-elite-full-mainnet}"
REMOTE="/opt/binancex/predmarket-scanner"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

FILES=(
  elite_trader/mega_system_report.py
  elite_trader/mega_system_score.py
  elite_trader/mega_live.py
  elite_trader/mode_engines/mega_scoring.py
  scripts/mega_system_report.py
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
sudo cp /tmp/_elite_trader__mega_system_report.py elite_trader/mega_system_report.py
sudo cp /tmp/_elite_trader__mega_system_score.py elite_trader/mega_system_score.py
sudo cp /tmp/_elite_trader__mega_live.py elite_trader/mega_live.py
sudo cp /tmp/_elite_trader__mode_engines__mega_scoring.py elite_trader/mode_engines/mega_scoring.py
sudo cp /tmp/_scripts__mega_system_report.py scripts/mega_system_report.py
sudo cp /tmp/_scenarios__binance_elite_mega_9006_mainnet.env scenarios/binance_elite_mega_9006_mainnet.env
sudo chown -R pro:pro elite_trader scripts scenarios 2>/dev/null || true
export MEGA_INSTANCE_ID=9006
python3 scripts/mega_system_report.py --no-telegram --hours 168
grep -E '^MEGA_SYSTEM_(REPORT|SCORE)' scenarios/binance_elite_mega_9006_mainnet.env | head -12
echo '=== restart 9006 ==='
sudo systemctl restart binance-elite-9006-mainnet
sleep 35
systemctl is-active binance-elite-9006-mainnet
"

echo "gcp_9006_p1_p2_system tamam."
