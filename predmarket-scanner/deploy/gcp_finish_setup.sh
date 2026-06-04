#!/usr/bin/env bash
# Resize/sync sonrası tek komut: kod sync + panel auth + lab + GCP env
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PROJECT="${GCP_PROJECT:-project-5f8843cb-1905-4297-af4}"
ZONE="${GCP_ZONE:-asia-northeast1-a}"
INSTANCE="${GCP_INSTANCE:-elite-full-mainnet}"
REMOTE="/opt/binancex/predmarket-scanner"

echo "=== [1/4] Kod sync ==="
GCP_PROJECT="${PROJECT}" bash deploy/gcp_sync_code_gcloud.sh

echo ""
echo "=== [2/4] Panel auth (x / x369) ==="
PANEL_AUTH_USER=x PANEL_AUTH_PASSWORD=x369 GCP_PROJECT="${PROJECT}" bash deploy/gcp_panel_auth.sh

echo ""
echo "=== [3/4] Sunucu env + systemd ==="
gcloud compute ssh "${INSTANCE}" --zone="${ZONE}" --project="${PROJECT}" --command="
set -e
ENV=${REMOTE}/.env
touch \"\${ENV}\"
grep -q '^GCP_PROJECT=' \"\${ENV}\" || echo 'GCP_PROJECT=${PROJECT}' >> \"\${ENV}\"
grep -q '^ADMIN_PANEL_PASSWORD=' \"\${ENV}\" || echo 'ADMIN_PANEL_PASSWORD=x369' >> \"\${ENV}\"
sudo cp ${REMOTE}/deploy/binance-elite-9007-mainnet.service /etc/systemd/system/
sudo systemctl daemon-reload
"

echo ""
echo "=== [4/4] Lab bootstrap + servisler ==="
GCP_PROJECT="${PROJECT}" bash deploy/gcp_lab_setup.sh

echo ""
echo "Tamam. Paneller: http://34.146.107.66:9085 9086 9087 — kullanıcı x, şifre x369"
