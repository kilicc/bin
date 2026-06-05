#!/usr/bin/env bash
# SSH timeout düzelt — firewall + VM network tag
# Kullanım: export GCP_PROJECT=... && bash deploy/gcp_fix_ssh.sh
set -euo pipefail

PROJECT="${GCP_PROJECT:-}"
ZONE="${GCP_ZONE:-asia-northeast1-a}"
INSTANCE="${GCP_INSTANCE:-elite-full-mainnet}"
INSTANCE_TAG="${GCP_INSTANCE_TAG:-elite-full}"
FIREWALL_SSH="${GCP_FIREWALL_SSH:-elite-full-allow-ssh}"

if [[ -z "${PROJECT}" ]]; then
  PROJECT=$(gcloud config get-value project 2>/dev/null || true)
fi
if [[ -z "${PROJECT}" || "${PROJECT}" == "(unset)" ]]; then
  echo "GCP_PROJECT ayarla veya: gcloud config set project PROJE_ID" >&2
  exit 1
fi

echo "=== GCP SSH Fix ==="
echo "Proje: ${PROJECT} | VM: ${INSTANCE} | Zone: ${ZONE}"

echo ""
echo "[1] VM durumu"
if ! gcloud compute instances describe "${INSTANCE}" --zone="${ZONE}" --project="${PROJECT}" &>/dev/null; then
  echo "VM bulunamadı: ${INSTANCE} (${ZONE})"
  echo "Mevcut VM'ler:"
  gcloud compute instances list --project="${PROJECT}"
  exit 1
fi

STATUS=$(gcloud compute instances describe "${INSTANCE}" --zone="${ZONE}" --project="${PROJECT}" \
  --format='get(status)')
EXT_IP=$(gcloud compute instances describe "${INSTANCE}" --zone="${ZONE}" --project="${PROJECT}" \
  --format='get(networkInterfaces[0].accessConfigs[0].natIP)')
TAGS=$(gcloud compute instances describe "${INSTANCE}" --zone="${ZONE}" --project="${PROJECT}" \
  --format='get(tags.items)')

echo "  Status: ${STATUS}"
echo "  External IP: ${EXT_IP:-YOK — Ephemeral IP veya VM durmuş}"
echo "  Tags: ${TAGS:-—}"

if [[ "${STATUS}" != "RUNNING" ]]; then
  echo ""
  echo "VM çalışmıyor — başlatılıyor..."
  gcloud compute instances start "${INSTANCE}" --zone="${ZONE}" --project="${PROJECT}"
  echo "30 saniye bekleniyor..."
  sleep 30
  EXT_IP=$(gcloud compute instances describe "${INSTANCE}" --zone="${ZONE}" --project="${PROJECT}" \
    --format='get(networkInterfaces[0].accessConfigs[0].natIP)')
  echo "  Yeni External IP: ${EXT_IP}"
fi

echo ""
echo "[2] Network tag: ${INSTANCE_TAG}"
if [[ "${TAGS}" != *"${INSTANCE_TAG}"* ]]; then
  gcloud compute instances add-tags "${INSTANCE}" \
    --zone="${ZONE}" \
    --project="${PROJECT}" \
    --tags="${INSTANCE_TAG}"
  echo "  Tag eklendi: ${INSTANCE_TAG}"
else
  echo "  Tag zaten var"
fi

echo ""
echo "[3] Firewall tcp:22"
if ! gcloud compute firewall-rules describe "${FIREWALL_SSH}" --project="${PROJECT}" &>/dev/null; then
  gcloud compute firewall-rules create "${FIREWALL_SSH}" \
    --project="${PROJECT}" \
    --direction=INGRESS \
    --priority=1000 \
    --network=default \
    --action=ALLOW \
    --rules=tcp:22 \
    --source-ranges=0.0.0.0/0 \
    --target-tags="${INSTANCE_TAG}" \
    --description="SSH for elite-full VM"
  echo "  Kural oluşturuldu: ${FIREWALL_SSH}"
else
  echo "  Kural mevcut: ${FIREWALL_SSH}"
fi

# Yedek: tüm instance'lara SSH (tag sorunu kalırsa)
FALLBACK="default-allow-ssh-custom"
if ! gcloud compute firewall-rules describe "${FALLBACK}" --project="${PROJECT}" &>/dev/null; then
  if ! gcloud compute firewall-rules describe default-allow-ssh --project="${PROJECT}" &>/dev/null; then
    gcloud compute firewall-rules create "${FALLBACK}" \
      --project="${PROJECT}" \
      --direction=INGRESS \
      --priority=65534 \
      --network=default \
      --action=ALLOW \
      --rules=tcp:22 \
      --source-ranges=0.0.0.0/0 \
      --description="SSH all instances (fallback)"
    echo "  Fallback kural: ${FALLBACK} (tüm VM'lere SSH)"
  else
    echo "  default-allow-ssh zaten var"
  fi
fi

echo ""
echo "[4] Statik IP (elite-full-ip)"
STATIC_IP=$(gcloud compute addresses describe elite-full-ip \
  --region=asia-northeast1 --project="${PROJECT}" --format='get(address)' 2>/dev/null || echo "")
if [[ -n "${STATIC_IP}" ]]; then
  echo "  Rezerve statik IP: ${STATIC_IP}"
  if [[ "${EXT_IP}" != "${STATIC_IP}" ]]; then
    echo "  UYARI: VM IP (${EXT_IP}) statik IP (${STATIC_IP}) ile uyuşmuyor!"
    echo "  SSH için VM'nin gerçek IP'sini kullan: ssh ubuntu@${EXT_IP}"
  fi
fi

echo ""
echo "=== Tamam ==="
echo "Mac'ten dene:"
echo "  ssh -o ConnectTimeout=15 ubuntu@${EXT_IP}"
echo ""
echo "Hâlâ timeout ise Console → VM → SSH (tarayıcı) kullan."
echo "Console SSH çalışıp Mac çalışmıyorsa ISP/antivirüs port 22 engelliyor olabilir."
