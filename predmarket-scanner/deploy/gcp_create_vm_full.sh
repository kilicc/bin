#!/usr/bin/env bash
# GCP Compute Engine — Full stack VM (9005 + 9006 + 9007 + Admin/Lab)
set -euo pipefail

PROJECT="${GCP_PROJECT:-}"
ZONE="${GCP_ZONE:-asia-northeast1-a}"
REGION="${GCP_REGION:-asia-northeast1}"
INSTANCE="${GCP_INSTANCE:-elite-full-mainnet}"
MACHINE="${GCP_MACHINE_TYPE:-e2-standard-4}"
BOOT_DISK_GB="${GCP_BOOT_DISK_GB:-100}"
DATA_DISK_GB="${GCP_DATA_DISK_GB:-100}"
DATA_DISK="${GCP_DATA_DISK:-elite-full-data}"
STATIC_IP_NAME="${GCP_STATIC_IP:-elite-full-ip}"
SSH_USER="${GCP_SSH_USER:-$USER}"
FIREWALL="${GCP_FIREWALL:-elite-full-allow-web}"
SA_EMAIL="${GCP_SA_EMAIL:-}"
INSTANCE_TAG="${GCP_INSTANCE_TAG:-elite-full}"

if [[ -z "${PROJECT}" ]]; then
  PROJECT=$(gcloud config get-value project 2>/dev/null || true)
fi
if [[ -z "${PROJECT}" || "${PROJECT}" == "(unset)" ]]; then
  echo "GCP_PROJECT ayarlayın veya önce: bash deploy/gcp_project_setup.sh" >&2
  exit 1
fi

echo "Proje: ${PROJECT} | Bölge: ${REGION} | VM: ${INSTANCE} | ${MACHINE}"

if ! gcloud compute addresses describe "${STATIC_IP_NAME}" --region="${REGION}" &>/dev/null; then
  echo "Statik IP yok — önce: bash deploy/gcp_project_setup.sh" >&2
  exit 1
fi
STATIC_IP=$(gcloud compute addresses describe "${STATIC_IP_NAME}" --region="${REGION}" --format='get(address)')
echo "Statik IP: ${STATIC_IP}"

if ! gcloud compute disks describe "${DATA_DISK}" --zone="${ZONE}" &>/dev/null; then
  gcloud compute disks create "${DATA_DISK}" \
    --zone="${ZONE}" \
    --size="${DATA_DISK_GB}GB" \
    --type=pd-balanced
fi

if ! gcloud compute firewall-rules describe "${FIREWALL}" &>/dev/null; then
  gcloud compute firewall-rules create "${FIREWALL}" \
    --project="${PROJECT}" \
    --direction=INGRESS \
    --priority=1000 \
    --network=default \
    --action=ALLOW \
    --rules=tcp:22,tcp:80,tcp:443,tcp:9085,tcp:9086,tcp:9087 \
    --source-ranges=0.0.0.0/0 \
    --target-tags="${INSTANCE_TAG}"
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
STARTUP_FILE="${SCRIPT_DIR}/gcp_startup_elite_full.sh"

SA_ARGS=()
if [[ -n "${SA_EMAIL}" ]]; then
  SA_ARGS=(--service-account="${SA_EMAIL}" --scopes=https://www.googleapis.com/auth/cloud-platform)
fi

if gcloud compute instances describe "${INSTANCE}" --zone="${ZONE}" &>/dev/null; then
  echo "VM zaten var: ${INSTANCE}"
else
  gcloud compute instances create "${INSTANCE}" \
    --project="${PROJECT}" \
    --zone="${ZONE}" \
    --machine-type="${MACHINE}" \
    --tags="${INSTANCE_TAG}" \
    --address="${STATIC_IP}" \
    --boot-disk-size="${BOOT_DISK_GB}GB" \
    --boot-disk-type=pd-balanced \
    --image-family=ubuntu-2204-lts \
    --image-project=ubuntu-os-cloud \
    --disk="name=${DATA_DISK},device-name=elite-full-data,mode=rw,boot=no,auto-delete=no" \
    --metadata-from-file=startup-script="${STARTUP_FILE}" \
    "${SA_ARGS[@]}"
  echo "VM oluşturuldu."
fi

echo ""
echo "Sonraki adımlar:"
echo "  1. Binance API key IP whitelist (3 key) → ${STATIC_IP}"
echo "  2. Kod: bash deploy/gcp_sync_code.sh ${SSH_USER}@${STATIC_IP}"
echo "  3. Bootstrap (domain yok): ssh ${SSH_USER}@${STATIC_IP} 'PANEL_MODE=ports GCP_PROJECT=${PROJECT} bash -s' < deploy/gcp_bootstrap_full.sh"
echo "  4. Veri: bash deploy/gcp_migrate_data_full.sh ${SSH_USER}@${STATIC_IP}"
echo "  5. Go-live: bash scripts/gcp_go_live_check.sh"
