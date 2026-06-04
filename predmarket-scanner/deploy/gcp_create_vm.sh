#!/usr/bin/env bash
# GCP Compute Engine — Elite 9005 mainnet VM oluştur
# Önkoşul: gcloud auth login && gcloud config set project YOUR_PROJECT
set -euo pipefail

PROJECT="${GCP_PROJECT:-}"
ZONE="${GCP_ZONE:-asia-northeast1-a}"
REGION="${GCP_REGION:-asia-northeast1}"
INSTANCE="${GCP_INSTANCE:-elite-9005-mainnet}"
MACHINE="${GCP_MACHINE_TYPE:-c3-highcpu-4}"
BOOT_DISK_GB="${GCP_BOOT_DISK_GB:-50}"
DATA_DISK_GB="${GCP_DATA_DISK_GB:-50}"
DATA_DISK="${GCP_DATA_DISK:-elite-9005-data}"
STATIC_IP_NAME="${GCP_STATIC_IP:-elite-9005-ip}"
SSH_USER="${GCP_SSH_USER:-$USER}"
FIREWALL="${GCP_FIREWALL:-elite-9005-allow-web}"

if [[ -z "${PROJECT}" ]]; then
  PROJECT=$(gcloud config get-value project 2>/dev/null || true)
fi
if [[ -z "${PROJECT}" || "${PROJECT}" == "(unset)" ]]; then
  echo "GCP_PROJECT ayarlayın: export GCP_PROJECT=your-project-id" >&2
  exit 1
fi

echo "Proje: ${PROJECT} | Bölge: ${REGION} | VM: ${INSTANCE}"

if ! gcloud compute addresses describe "${STATIC_IP_NAME}" --region="${REGION}" &>/dev/null; then
  gcloud compute addresses create "${STATIC_IP_NAME}" --region="${REGION}"
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
    --rules=tcp:22,tcp:80,tcp:443 \
    --source-ranges=0.0.0.0/0 \
    --target-tags=elite-9005
  echo "SSH için IP kısıtlaması önerilir: gcloud compute firewall-rules update ${FIREWALL} --source-ranges=YOUR_IP/32"
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
STARTUP_FILE="${SCRIPT_DIR}/gcp_startup_elite_9005.sh"

if gcloud compute instances describe "${INSTANCE}" --zone="${ZONE}" &>/dev/null; then
  echo "VM zaten var: ${INSTANCE}"
else
  gcloud compute instances create "${INSTANCE}" \
    --project="${PROJECT}" \
    --zone="${ZONE}" \
    --machine-type="${MACHINE}" \
    --tags=elite-9005 \
    --address="${STATIC_IP}" \
    --boot-disk-size="${BOOT_DISK_GB}GB" \
    --boot-disk-type=pd-balanced \
    --image-family=ubuntu-2204-lts \
    --image-project=ubuntu-os-cloud \
    --disk="name=${DATA_DISK},device-name=elite-9005-data,mode=rw,boot=no,auto-delete=no" \
    --metadata-from-file=startup-script="${STARTUP_FILE}"
  echo "VM oluşturuldu."
fi

echo ""
echo "Sonraki adımlar:"
echo "  1. Binance API key IP whitelist → ${STATIC_IP}"
echo "  2. rsync kod: ./deploy/gcp_sync_code.sh ${SSH_USER}@${STATIC_IP}"
echo "  3. SSH bootstrap: ssh ${SSH_USER}@${STATIC_IP} 'bash -s' < deploy/gcp_bootstrap.sh"
echo "  4. Veri taşı: ./deploy/gcp_migrate_data.sh ${SSH_USER}@${STATIC_IP}"
echo "  5. Go-live: ./scripts/gcp_go_live_check.sh https://panel.example.com"
