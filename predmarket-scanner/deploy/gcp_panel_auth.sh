#!/usr/bin/env bash
# nginx Basic Auth — varsayılan x / x369
set -euo pipefail

PROJECT="${GCP_PROJECT:-project-5f8843cb-1905-4297-af4}"
ZONE="${GCP_ZONE:-asia-northeast1-a}"
INSTANCE="${GCP_INSTANCE:-elite-full-mainnet}"
USER="${PANEL_AUTH_USER:-x}"
PASS="${PANEL_AUTH_PASSWORD:-x369}"

gcloud compute ssh "${INSTANCE}" --zone="${ZONE}" --project="${PROJECT}" --command="
set -e
printf '${PASS}\n' | sudo htpasswd -ci /etc/nginx/.htpasswd_elite '${USER}'
# Tarayıcı bazen admin yazar — aynı şifre ile alias
sudo htpasswd -b /etc/nginx/.htpasswd_elite admin '${PASS}' 2>/dev/null || true
sudo nginx -t
sudo systemctl reload nginx
echo 'Panel nginx auth: user=${USER} (alias admin)'
"

echo "Panel giriş: ${USER} / ${PASS}"
