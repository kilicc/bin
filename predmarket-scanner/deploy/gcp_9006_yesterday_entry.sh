#!/usr/bin/env bash
# 9006 — dünkü giriş (vol scan + flash); rejim/cascade/coin-rank kapalı; kapanış API doğrulama korunur
set -euo pipefail

PROJECT="${GCP_PROJECT:-project-5f8843cb-1905-4297-af4}"
ZONE="${GCP_ZONE:-asia-northeast1-a}"
INSTANCE="${GCP_INSTANCE:-elite-full-mainnet}"
REMOTE="/opt/binancex/predmarket-scanner"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

FILES=(
  elite_trader/mega_volatility.py
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
sudo cp /tmp/_elite_trader__mega_volatility.py elite_trader/mega_volatility.py
sudo cp /tmp/_scenarios__binance_elite_mega_9006_mainnet.env scenarios/binance_elite_mega_9006_mainnet.env
sudo chown -R pro:pro elite_trader scenarios 2>/dev/null || true
grep -E '^MEGA_REGIME_AUTO|^MEGA_REGIME_LOCK|^MEGA_MIN_SCORE|^MEGA_MIN_MOVE|^MEGA_BTC_CASCADE|^MEGA_COIN_RANK|^MEGA_FLASH_REVERSAL|^MEGA_CLOSED_REQUIRE' scenarios/binance_elite_mega_9006_mainnet.env
echo '=== restart 9006 (no data wipe) ==='
sudo systemctl restart binance-elite-9006-mainnet
sleep 35
systemctl is-active binance-elite-9006-mainnet
"

echo "gcp_9006_yesterday_entry tamam."
