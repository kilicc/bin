#!/usr/bin/env bash
# MEGA 9006 — P2.5 coin rank + yıldız SL + $1000 slot
set -euo pipefail

PROJECT="${GCP_PROJECT:-project-5f8843cb-1905-4297-af4}"
ZONE="${GCP_ZONE:-asia-northeast1-a}"
INSTANCE="${GCP_INSTANCE:-elite-full-mainnet}"
REMOTE="/opt/binancex/predmarket-scanner"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

FILES=(
  elite_trader/capital_slots.py
  elite_trader/mega_coin_rank.py
  elite_trader/mega_coin_watch.py
  elite_trader/mega_star_sl.py
  elite_trader/mega_slot_swap.py
  elite_trader/mega_live.py
  elite_trader/mode_engines/mega_scoring.py
  elite_trader/panel_strategy.py
  scripts/mega_coin_rank.py
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
sudo cp /tmp/_elite_trader__capital_slots.py elite_trader/capital_slots.py
sudo cp /tmp/_elite_trader__mega_coin_rank.py elite_trader/mega_coin_rank.py
sudo cp /tmp/_elite_trader__mega_coin_watch.py elite_trader/mega_coin_watch.py
sudo cp /tmp/_elite_trader__mega_star_sl.py elite_trader/mega_star_sl.py
sudo cp /tmp/_elite_trader__mega_slot_swap.py elite_trader/mega_slot_swap.py
sudo cp /tmp/_elite_trader__mega_live.py elite_trader/mega_live.py
sudo cp /tmp/_elite_trader__mode_engines__mega_scoring.py elite_trader/mode_engines/mega_scoring.py
sudo cp /tmp/_elite_trader__panel_strategy.py elite_trader/panel_strategy.py
sudo cp /tmp/_scripts__mega_coin_rank.py scripts/mega_coin_rank.py
sudo cp /tmp/_scenarios__binance_elite_mega_9006_mainnet.env scenarios/binance_elite_mega_9006_mainnet.env
sudo chown -R pro:pro elite_trader scripts scenarios 2>/dev/null || true
export MEGA_INSTANCE_ID=9006
python3 scripts/mega_coin_rank.py --no-telegram --hours 168
grep -E '^MEGA_(COIN_RANK|STAR_SL|SLOT_|MIN_SLOT|STAKE_USE|SMALL_)' scenarios/binance_elite_mega_9006_mainnet.env | head -20
echo '=== restart 9006 ==='
sudo systemctl restart binance-elite-9006-mainnet
sleep 35
systemctl is-active binance-elite-9006-mainnet
"

echo "gcp_9006_p25_coin_rank_slots tamam."
