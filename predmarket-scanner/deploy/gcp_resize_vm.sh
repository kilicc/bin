#!/usr/bin/env bash
# VM büyütme — e2-standard-4 → e2-standard-8 (veya GCP_MACHINE_TYPE)
set -euo pipefail

PROJECT="${GCP_PROJECT:-}"
ZONE="${GCP_ZONE:-asia-northeast1-a}"
INSTANCE="${GCP_INSTANCE:-elite-full-mainnet}"
NEW_TYPE="${GCP_MACHINE_TYPE:-e2-standard-8}"

if [[ -z "${PROJECT}" ]]; then
  PROJECT=$(gcloud config get-value project 2>/dev/null || true)
fi
if [[ -z "${PROJECT}" || "${PROJECT}" == "(unset)" ]]; then
  echo "GCP_PROJECT ayarla" >&2
  exit 1
fi

CUR=$(gcloud compute instances describe "${INSTANCE}" --zone="${ZONE}" --project="${PROJECT}" \
  --format='get(machineType)' | sed 's|.*/||')
echo "Mevcut: ${CUR} → Yeni: ${NEW_TYPE}"

if [[ "${CUR}" == "${NEW_TYPE}" ]]; then
  echo "Zaten ${NEW_TYPE}"
  exit 0
fi

echo "VM durduruluyor..."
gcloud compute instances stop "${INSTANCE}" --zone="${ZONE}" --project="${PROJECT}" --quiet

echo "Makine tipi değiştiriliyor..."
gcloud compute instances set-machine-type "${INSTANCE}" \
  --zone="${ZONE}" \
  --project="${PROJECT}" \
  --machine-type="${NEW_TYPE}"

echo "VM başlatılıyor..."
gcloud compute instances start "${INSTANCE}" --zone="${ZONE}" --project="${PROJECT}" --quiet

echo "30s bekleniyor..."
sleep 30

gcloud compute ssh "${INSTANCE}" --zone="${ZONE}" --project="${PROJECT}" --command="
  sudo systemctl start binance-elite-9005-mainnet binance-elite-9006-mainnet binance-elite-9007-mainnet elite-full-supervisor nginx
  uptime
  free -h | head -2
" 2>/dev/null || echo "SSH ile servisleri manuel başlat"

echo ""
echo "Resize tamam: ${NEW_TYPE}"
