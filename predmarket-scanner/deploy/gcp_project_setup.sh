#!/usr/bin/env bash
# GCP proje hazırlığı — API enable, service account, GCS bucket, statik IP
# Önkoşul: gcloud auth login && gcloud config set project YOUR_PROJECT
set -euo pipefail

PROJECT="${GCP_PROJECT:-}"
REGION="${GCP_REGION:-asia-northeast1}"
ZONE="${GCP_ZONE:-asia-northeast1-a}"
SA_NAME="${GCP_SA_NAME:-binancex-bot}"
SA_EMAIL="${SA_NAME}@${PROJECT}.iam.gserviceaccount.com"
BUCKET="${GCS_BACKUP_BUCKET:-}"
STATIC_IP_NAME="${GCP_STATIC_IP:-elite-full-ip}"
INSTANCE_TAG="${GCP_INSTANCE_TAG:-elite-full}"

if [[ -z "${PROJECT}" ]]; then
  PROJECT=$(gcloud config get-value project 2>/dev/null || true)
fi
if [[ -z "${PROJECT}" || "${PROJECT}" == "(unset)" ]]; then
  echo "GCP_PROJECT ayarlayın: export GCP_PROJECT=your-project-id" >&2
  exit 1
fi
if [[ -z "${BUCKET}" ]]; then
  BUCKET="${PROJECT}-binancex-backups"
fi

echo "=== GCP Proje Kurulumu ==="
echo "Proje: ${PROJECT} | Bölge: ${REGION} | Bucket: ${BUCKET}"

APIS=(
  compute.googleapis.com
  aiplatform.googleapis.com
  secretmanager.googleapis.com
  storage.googleapis.com
  monitoring.googleapis.com
  logging.googleapis.com
  iam.googleapis.com
)
for api in "${APIS[@]}"; do
  echo "API: ${api}"
  gcloud services enable "${api}" --project="${PROJECT}" --quiet
done

if ! gcloud iam service-accounts describe "${SA_EMAIL}" --project="${PROJECT}" &>/dev/null; then
  gcloud iam service-accounts create "${SA_NAME}" \
    --project="${PROJECT}" \
    --display-name="BinanceX Trading Bot"
  echo "Service account oluşturuldu: ${SA_EMAIL}"
else
  echo "Service account mevcut: ${SA_EMAIL}"
fi

for role in roles/aiplatform.user roles/secretmanager.secretAccessor roles/storage.objectAdmin roles/logging.logWriter roles/monitoring.metricWriter; do
  gcloud projects add-iam-policy-binding "${PROJECT}" \
    --member="serviceAccount:${SA_EMAIL}" \
    --role="${role}" \
    --quiet >/dev/null
  echo "IAM: ${role}"
done

if ! gsutil ls -b "gs://${BUCKET}" &>/dev/null; then
  gsutil mb -p "${PROJECT}" -l "${REGION}" "gs://${BUCKET}"
  gsutil versioning set on "gs://${BUCKET}"
  echo "GCS bucket: gs://${BUCKET}"
else
  echo "GCS bucket mevcut: gs://${BUCKET}"
fi

if ! gcloud compute addresses describe "${STATIC_IP_NAME}" --region="${REGION}" &>/dev/null; then
  gcloud compute addresses create "${STATIC_IP_NAME}" --region="${REGION}"
fi
STATIC_IP=$(gcloud compute addresses describe "${STATIC_IP_NAME}" --region="${REGION}" --format='get(address)')
echo "Statik IP: ${STATIC_IP}"

FIREWALL="${GCP_FIREWALL:-elite-full-allow-web}"
if ! gcloud compute firewall-rules describe "${FIREWALL}" --project="${PROJECT}" &>/dev/null; then
  gcloud compute firewall-rules create "${FIREWALL}" \
    --project="${PROJECT}" \
    --direction=INGRESS \
    --priority=1000 \
    --network=default \
    --action=ALLOW \
    --rules=tcp:22,tcp:80,tcp:443,tcp:9085,tcp:9086,tcp:9087 \
    --source-ranges=0.0.0.0/0 \
    --target-tags="${INSTANCE_TAG}"
  echo "Firewall: ${FIREWALL} (SSH + panel 9085/9086/9087)"
fi

PANEL_FW="${GCP_PANEL_FIREWALL:-elite-full-panel-ports}"
if ! gcloud compute firewall-rules describe "${PANEL_FW}" --project="${PROJECT}" &>/dev/null; then
  gcloud compute firewall-rules create "${PANEL_FW}" \
    --project="${PROJECT}" \
    --direction=INGRESS \
    --priority=1001 \
    --network=default \
    --action=ALLOW \
    --rules=tcp:9085,tcp:9086,tcp:9087 \
    --source-ranges=0.0.0.0/0 \
    --target-tags="${INSTANCE_TAG}" \
    --description="Elite panel ports (domain yok)" 2>/dev/null || true
fi

echo ""
echo "=== Kurulum tamam ==="
echo "Statik IP (Binance whitelist): ${STATIC_IP}"
echo "GCS bucket: gs://${BUCKET}"
echo "Service account: ${SA_EMAIL}"
echo ""
echo "Sonraki adım:"
echo "  export GCP_PROJECT=${PROJECT} GCS_BACKUP_BUCKET=${BUCKET}"
echo "  bash deploy/gcp_create_vm_full.sh"
