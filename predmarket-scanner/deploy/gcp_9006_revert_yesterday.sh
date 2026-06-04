#!/usr/bin/env bash
# 9006 — dünkü giriş/çıkış ayarları (bounce kapalı, TP/scalp geri); panel+close-sync korunur; sıfırlama YOK
set -euo pipefail

PROJECT="${GCP_PROJECT:-project-5f8843cb-1905-4297-af4}"
ZONE="${GCP_ZONE:-asia-northeast1-a}"
INSTANCE="${GCP_INSTANCE:-elite-full-mainnet}"
REMOTE="/opt/binancex/predmarket-scanner"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

FILES=(
  elite_trader/mega_live.py
  elite_trader/btc_flash_cascade.py
  elite_trader/exchange_fill_truth.py
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
sudo cp /tmp/_elite_trader__btc_flash_cascade.py elite_trader/btc_flash_cascade.py
sudo cp /tmp/_elite_trader__exchange_fill_truth.py elite_trader/exchange_fill_truth.py
sudo cp /tmp/_scenarios__binance_elite_mega_9006_mainnet.env scenarios/binance_elite_mega_9006_mainnet.env
sudo chown -R pro:pro elite_trader scenarios 2>/dev/null || true
grep -E '^MEGA_BOUNCE|^MEGA_PEAK_CAPTURE|^MEGA_NET_TP_LOCK|^MEGA_SCALP|^MEGA_SPIKE_BYPASS|^MEGA_MIN_CLOSE_NET' scenarios/binance_elite_mega_9006_mainnet.env
echo '=== restart 9006 (no data wipe) ==='
sudo systemctl restart binance-elite-9006-mainnet
sleep 35
systemctl is-active binance-elite-9006-mainnet
"

echo "gcp_9006_revert_yesterday tamam."
