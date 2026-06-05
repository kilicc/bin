#!/usr/bin/env bash
# Mac → GCP kod sync (gcloud SSH anahtarı ile)
set -euo pipefail

PROJECT="${GCP_PROJECT:-}"
ZONE="${GCP_ZONE:-asia-northeast1-a}"
INSTANCE="${GCP_INSTANCE:-elite-full-mainnet}"
REMOTE_ROOT="${GCP_REMOTE_ROOT:-/opt/binancex/predmarket-scanner}"
SSH_KEY="${GCP_SSH_KEY:-$HOME/.ssh/google_compute_engine}"
REMOTE_USER="${GCP_SSH_USER:-pro}"

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ -z "${PROJECT}" ]]; then
  PROJECT=$(gcloud config get-value project 2>/dev/null || true)
fi
if [[ -z "${PROJECT}" || "${PROJECT}" == "(unset)" ]]; then
  echo "GCP_PROJECT ayarla" >&2
  exit 1
fi

if [[ ! -f "${SSH_KEY}" ]]; then
  echo "SSH key yok: ${SSH_KEY}" >&2
  echo "Önce: gcloud compute ssh ${INSTANCE} --zone=${ZONE} --project=${PROJECT}" >&2
  exit 1
fi

STATIC_IP=$(gcloud compute instances describe "${INSTANCE}" \
  --zone="${ZONE}" --project="${PROJECT}" \
  --format='get(networkInterfaces[0].accessConfigs[0].natIP)')

echo "=== GCP kod sync ==="
echo "VM: ${INSTANCE} @ ${STATIC_IP} → ${REMOTE_ROOT}"

echo "[1] Uzak dizin..."
gcloud compute ssh "${INSTANCE}" \
  --zone="${ZONE}" \
  --project="${PROJECT}" \
  --command="sudo mkdir -p ${REMOTE_ROOT} && sudo chown -R \$(whoami):\$(whoami) /opt/binancex"

echo "[2] rsync (5-15 dk)..."
# Botların çalışırken yazdığı dosyalar checksum hatası (exit 23) verir — sunucu kendi runtime state'ini tutar
RSYNC_EXCLUDES=(
  --exclude '.venv/'
  --exclude '__pycache__/'
  --exclude '*.pyc'
  --exclude '.git/'
  --exclude 'logs/'
  --exclude '.pids/'
  --exclude 'data/backups/'
  --exclude 'node_modules/'
  --exclude 'data/mega_market_regime.json'
  --exclude 'data/price_cache.json'
  --exclude 'data/*.db-shm'
  --exclude 'data/*.db-wal'
  --exclude 'data/mode_reject_buffers/'
)

set +e
rsync -avz --progress \
  -e "ssh -i ${SSH_KEY} -o StrictHostKeyChecking=no" \
  "${RSYNC_EXCLUDES[@]}" \
  ./ "${REMOTE_USER}@${STATIC_IP}:${REMOTE_ROOT}/"
rsync_rc=$?
set -e

if [[ "${rsync_rc}" -eq 0 ]]; then
  echo ""
  echo "Kod sync OK."
elif [[ "${rsync_rc}" -eq 23 ]]; then
  echo ""
  echo "Kod sync tamam (uyarı: rsync 23 — çalışan bot dosyası değişti, kod yine aktarıldı)." >&2
else
  echo "rsync hata kodu: ${rsync_rc}" >&2
  exit "${rsync_rc}"
fi
