#!/usr/bin/env bash
# MEGA 9006 — dip dönüş LONG / fade-bounce SHORT düzeltmesi (veri silmez)
set -euo pipefail

PROJECT="${GCP_PROJECT:-project-5f8843cb-1905-4297-af4}"
ZONE="${GCP_ZONE:-asia-northeast1-a}"
INSTANCE="${GCP_INSTANCE:-elite-full-mainnet}"
REMOTE="/opt/binancex/predmarket-scanner"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

FILES=(
  elite_trader/btc_flash_cascade.py
  elite_trader/mega_direction_guard.py
  elite_trader/btc_macro_feed.py
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
sudo cp /tmp/_elite_trader__btc_flash_cascade.py elite_trader/btc_flash_cascade.py
sudo cp /tmp/_elite_trader__mega_direction_guard.py elite_trader/mega_direction_guard.py
sudo cp /tmp/_elite_trader__btc_macro_feed.py elite_trader/btc_macro_feed.py
sudo cp /tmp/_scenarios__binance_elite_mega_9006_mainnet.env scenarios/binance_elite_mega_9006_mainnet.env
sudo chown -R pro:pro elite_trader scenarios 2>/dev/null || true
grep -E '^MEGA_BOUNCE_FAVOR_LONG|^MEGA_MACRO_BOUNCE' scenarios/binance_elite_mega_9006_mainnet.env || true
echo '=== restart 9006 (5m boot observe) ==='
sudo systemctl restart binance-elite-9006-mainnet
sleep 35
systemctl is-active binance-elite-9006-mainnet
"

echo "gcp_9006_bounce_favor tamam."
