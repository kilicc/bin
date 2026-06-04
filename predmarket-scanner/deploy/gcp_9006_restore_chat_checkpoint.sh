#!/usr/bin/env bash
# 9006 — bu sohbet checkpoint (P0/P1 açık, P2 kapı=0, underwater canlıda kapalı, boot observe kapalı)
# Veri silmez; yalnız kod + env + restart
set -euo pipefail

PROJECT="${GCP_PROJECT:-project-5f8843cb-1905-4297-af4}"
ZONE="${GCP_ZONE:-asia-northeast1-a}"
INSTANCE="${GCP_INSTANCE:-elite-full-mainnet}"
REMOTE="/opt/binancex/predmarket-scanner"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

FILES=(
  elite_trader/mega_live.py
  elite_trader/fee_economics.py
  elite_trader/panel_strategy.py
  elite_trader/mega_system_context.py
  elite_trader/mega_system_report.py
  elite_trader/mega_system_score.py
  elite_trader/mode_engines/mega_scoring.py
  elite_trader/telegram_notify.py
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
sudo cp /tmp/_elite_trader__fee_economics.py elite_trader/fee_economics.py
sudo cp /tmp/_elite_trader__panel_strategy.py elite_trader/panel_strategy.py
sudo cp /tmp/_elite_trader__mega_system_context.py elite_trader/mega_system_context.py
sudo cp /tmp/_elite_trader__mega_system_report.py elite_trader/mega_system_report.py
sudo cp /tmp/_elite_trader__mega_system_score.py elite_trader/mega_system_score.py
sudo cp /tmp/_elite_trader__mode_engines__mega_scoring.py elite_trader/mode_engines/mega_scoring.py
sudo cp /tmp/_elite_trader__telegram_notify.py elite_trader/telegram_notify.py
sudo cp /tmp/_scenarios__binance_elite_mega_9006_mainnet.env scenarios/binance_elite_mega_9006_mainnet.env
sudo chown -R pro:pro elite_trader scenarios 2>/dev/null || true
echo '=== checkpoint env ==='
grep -E '^MEGA_SYSTEM_|^MEGA_UNDERWATER|^MEGA_BOOT|^MEGA_MARK_UNREAL|^MEGA_DISABLE_SL' scenarios/binance_elite_mega_9006_mainnet.env
echo '=== restart 9006 (no data wipe) ==='
sudo systemctl restart binance-elite-9006-mainnet
sleep 35
systemctl is-active binance-elite-9006-mainnet
"

echo "gcp_9006_restore_chat_checkpoint tamam."
