#!/usr/bin/env bash
# Full stack cutover — 9005 + 9006 + 9007 + lab verisi (DATA_PRESERVATION uyumlu)
set -euo pipefail

REMOTE="${1:-}"
SSH_KEY="${GCP_SSH_KEY:-$HOME/.ssh/google_compute_engine}"
PROJECT="${GCP_PROJECT:-}"
ZONE="${GCP_ZONE:-asia-northeast1-a}"
INSTANCE="${GCP_INSTANCE:-elite-full-mainnet}"
REMOTE_ROOT="/opt/binancex/predmarket-scanner"

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ -z "${PROJECT}" ]]; then
  PROJECT=$(gcloud config get-value project 2>/dev/null || true)
fi

if [[ -z "${REMOTE}" ]]; then
  if [[ -n "${PROJECT}" && "${PROJECT}" != "(unset)" ]]; then
    IP=$(gcloud compute instances describe "${INSTANCE}" \
      --zone="${ZONE}" --project="${PROJECT}" \
      --format='get(networkInterfaces[0].accessConfigs[0].natIP)' 2>/dev/null || true)
    REMOTE="pro@${IP}"
  else
    echo "Kullanım: $0 [pro@GCP_IP]" >&2
    echo "  veya: GCP_PROJECT=... $0" >&2
    exit 1
  fi
fi

if [[ -f "${SSH_KEY}" ]]; then
  export RSYNC_RSH="ssh -i ${SSH_KEY} -o StrictHostKeyChecking=no"
  SSH_CMD=(ssh -i "${SSH_KEY}" -o StrictHostKeyChecking=no)
else
  SSH_CMD=(ssh)
fi

_rsync() {
  rsync -avz "$@"
}

echo "=== Cutover → ${REMOTE} ==="
echo "=== Mac botları durduruluyor ==="
for ctl in elite_9005_process_ctl elite_9005_mainnet_process_ctl elite_9006_process_ctl elite_9007_process_ctl; do
  if [[ -x "scripts/${ctl}.sh" ]]; then
    "./scripts/${ctl}.sh" stop 0 2>/dev/null || "./scripts/${ctl}.sh" force-stop 2>/dev/null || true
  fi
done

TS=$(date -u +%Y%m%dT%H%M%SZ)
DB="data/binance_elite_8300_9005_state.db"
if [[ -f "${DB}" ]]; then
  cp "${DB}" "data/pre_gcp_cutover_${TS}.db"
  echo "9005 DB snapshot: data/pre_gcp_cutover_${TS}.db"
fi

echo "=== rsync 9005 korumalı veri ==="
PROTECTED_9005=(
  data/binance_elite_8300_9005_state.db
  data/elite_9005_trade_lessons.json
  data/elite_9005_learning_registry.json
  data/elite_9005_proposals.json
  data/elite_sl_emergency_registry.json
  data/elite_9005_loss_postmortem.json
  data/elite_9005_loss_postmortem.md
  data/parallel_universes.json
)
for f in "${PROTECTED_9005[@]}"; do
  [[ -f "${f}" ]] && _rsync "${f}" "${REMOTE}:${REMOTE_ROOT}/data/" || true
done
[[ -d data/deleted_archives ]] && _rsync data/deleted_archives/ "${REMOTE}:${REMOTE_ROOT}/data/deleted_archives/" || true

echo "=== rsync MEGA 9006/9007 veri ==="
[[ -d data/mega_9007 ]] && _rsync data/mega_9007/ "${REMOTE}:${REMOTE_ROOT}/data/mega_9007/" || true
[[ -d data/lab_9007 ]] && _rsync data/lab_9007/ "${REMOTE}:${REMOTE_ROOT}/data/lab_9007/" || true
[[ -d data/apex_master ]] && _rsync data/apex_master/ "${REMOTE}:${REMOTE_ROOT}/data/apex_master/" || true
[[ -d data/checkpoints ]] && _rsync data/checkpoints/ "${REMOTE}:${REMOTE_ROOT}/data/checkpoints/" 2>/dev/null || true

echo "=== rsync senaryo mainnet env ==="
_rsync \
  scenarios/binance_elite_8300_9005_mainnet.env \
  scenarios/binance_elite_mega_9006_mainnet.env \
  scenarios/binance_elite_mega_9007_mainnet.env \
  "${REMOTE}:${REMOTE_ROOT}/scenarios/"

echo "=== .env (3 API key set) ==="
if [[ ! -f .env ]]; then
  echo "UYARI: .env yok — sunucuda manuel oluşturun (deploy/BINANCE_API_KEYS_CHECKLIST.md)" >&2
else
  _rsync .env "${REMOTE}:${REMOTE_ROOT}/.env"
  "${SSH_CMD[@]}" "${REMOTE}" "chmod 600 ${REMOTE_ROOT}/.env"
fi

echo ""
echo "Cutover tamam. Sunucuda:"
echo "  gcloud compute ssh ${INSTANCE} --zone=${ZONE} --project=${PROJECT} --command=\"sudo systemctl start binance-elite-9005-mainnet binance-elite-9006-mainnet binance-elite-9007-mainnet elite-full-supervisor\""
echo "  bash scripts/gcp_go_live_check.sh"
