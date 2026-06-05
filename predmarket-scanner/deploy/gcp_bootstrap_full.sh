#!/usr/bin/env bash
# GCP VM ilk kurulum — Full stack (9005 + 9006 + 9007 + Admin/Lab)
set -euo pipefail

APP_ROOT="${APP_ROOT:-/opt/binancex/predmarket-scanner}"
APP_USER="${APP_USER:-$(whoami)}"
PANEL_MODE="${PANEL_MODE:-ports}"
PANEL_DOMAIN_9005="${PANEL_DOMAIN_9005:-9005.example.com}"
PANEL_DOMAIN_9006="${PANEL_DOMAIN_9006:-mega6.example.com}"
PANEL_DOMAIN_9007="${PANEL_DOMAIN_9007:-mega7.example.com}"
PANEL_AUTH_USER="${PANEL_AUTH_USER:-x}"
GCP_PROJECT="${GCP_PROJECT:-}"

echo "=== Elite Full Stack GCP bootstrap ==="
echo "APP_ROOT=${APP_ROOT}"

export DEBIAN_FRONTEND=noninteractive
sudo apt-get update -qq
sudo apt-get install -y -qq \
  python3.11 python3.11-venv python3-pip \
  git curl nginx apache2-utils certbot python3-certbot-nginx \
  ufw chrony sqlite3 rsync logrotate apt-transport-https ca-certificates gnupg

_install_gcloud_cli() {
  if command -v gsutil >/dev/null 2>&1; then
    return 0
  fi
  echo "google-cloud-cli (opsiyonel — GCS backup)..."
  if [[ ! -f /usr/share/keyrings/cloud.google.gpg ]]; then
    curl -fsSL https://packages.cloud.google.com/apt/doc/apt-key.gpg \
      | sudo gpg --dearmor -o /usr/share/keyrings/cloud.google.gpg
    echo "deb [signed-by=/usr/share/keyrings/cloud.google.gpg] https://packages.cloud.google.com/apt cloud-sdk main" \
      | sudo tee /etc/apt/sources.list.d/google-cloud-sdk.list >/dev/null
    sudo apt-get update -qq
  fi
  sudo apt-get install -y -qq google-cloud-cli 2>/dev/null || \
    echo "  gsutil atlandı — backup cron sonra kurulabilir"
}
_install_gcloud_cli || true

sudo systemctl enable --now chrony

if ! swapon --show | grep -q swapfile; then
  sudo fallocate -l 4G /swapfile || sudo dd if=/dev/zero of=/swapfile bs=1M count=4096
  sudo chmod 600 /swapfile
  sudo mkswap /swapfile
  sudo swapon /swapfile
  grep -q swapfile /etc/fstab || echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
  echo 'vm.swappiness=10' | sudo tee /etc/sysctl.d/99-trading.conf
  echo 'net.core.rmem_max = 16777216' | sudo tee -a /etc/sysctl.d/99-trading.conf
  echo 'net.ipv4.tcp_fastopen = 3' | sudo tee -a /etc/sysctl.d/99-trading.conf
  sudo sysctl --system
fi

sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw allow 9085/tcp
sudo ufw allow 9086/tcp
sudo ufw allow 9087/tcp
echo "y" | sudo ufw enable || true

DATA_MNT="/opt/binancex/data"
sudo mkdir -p "${DATA_MNT}" "${APP_ROOT}" "${APP_ROOT}/logs"
if mountpoint -q "${DATA_MNT}" 2>/dev/null; then
  echo "Veri diski mount OK: ${DATA_MNT}"
  if [[ ! -e "${APP_ROOT}/data" ]]; then
    ln -sfn "${DATA_MNT}" "${APP_ROOT}/data"
  fi
fi

if [[ -f "${APP_ROOT}/requirements.txt" ]]; then
  cd "${APP_ROOT}"
  python3.11 -m venv .venv
  .venv/bin/pip install -U pip wheel
  .venv/bin/pip install -r requirements.txt
  chmod +x run_binance_elite_*.sh scripts/*.sh deploy/*.sh 2>/dev/null || true
fi

sudo mkdir -p /etc/nginx/snippets
if [[ ! -f /etc/nginx/.htpasswd_elite ]]; then
  if [[ -n "${PANEL_AUTH_PASSWORD:-}" ]]; then
    printf '%s\n' "${PANEL_AUTH_PASSWORD}" | sudo htpasswd -ci /etc/nginx/.htpasswd_elite "${PANEL_AUTH_USER}"
    echo "Panel şifresi kaydedildi (${PANEL_AUTH_USER}, env)"
  elif [[ -t 0 ]]; then
    echo "Panel şifresi oluşturuluyor (${PANEL_AUTH_USER})..."
    sudo htpasswd -c /etc/nginx/.htpasswd_elite "${PANEL_AUTH_USER}"
  else
    echo "UYARI: PANEL_AUTH_PASSWORD env verin (non-interactive bootstrap)" >&2
    printf 'x369\n' | sudo htpasswd -ci /etc/nginx/.htpasswd_elite "${PANEL_AUTH_USER}" || true
  fi
fi

if [[ "${PANEL_MODE}" == "ports" ]] && [[ -f "${APP_ROOT}/deploy/nginx-elite-full-ports.conf" ]]; then
  echo "nginx: domain yok — port modu (9085/9086/9087)"
  sudo cp "${APP_ROOT}/deploy/nginx-elite-full-ports.conf" /etc/nginx/sites-available/elite-full-ports
  sudo ln -sf /etc/nginx/sites-available/elite-full-ports /etc/nginx/sites-enabled/elite-full-ports
  sudo rm -f /etc/nginx/sites-enabled/default /etc/nginx/sites-enabled/elite-full
  sudo nginx -t
  sudo systemctl enable nginx
  sudo systemctl reload nginx
elif [[ -f "${APP_ROOT}/deploy/nginx-elite-full.conf" ]]; then
  echo "nginx: subdomain modu (HTTPS)"
  sudo cp "${APP_ROOT}/deploy/nginx-elite-full.conf" /etc/nginx/sites-available/elite-full
  sudo sed -i "s/9005.example.com/${PANEL_DOMAIN_9005}/g" /etc/nginx/sites-available/elite-full
  sudo sed -i "s/mega6.example.com/${PANEL_DOMAIN_9006}/g" /etc/nginx/sites-available/elite-full
  sudo sed -i "s/mega7.example.com/${PANEL_DOMAIN_9007}/g" /etc/nginx/sites-available/elite-full
  sudo ln -sf /etc/nginx/sites-available/elite-full /etc/nginx/sites-enabled/elite-full
  sudo rm -f /etc/nginx/sites-enabled/default /etc/nginx/sites-enabled/elite-full-ports
  sudo nginx -t
  sudo systemctl enable nginx
  sudo systemctl reload nginx
fi

_install_svc() {
  local src="$1" dst="$2"
  sudo sed "s|/opt/binancex/predmarket-scanner|${APP_ROOT}|g; s|User=.*|User=${APP_USER}|g; s|Group=.*|Group=${APP_USER}|g" \
    "${APP_ROOT}/deploy/${src}" | sudo tee "/etc/systemd/system/${dst}" >/dev/null
}

for svc in binance-elite-9005-mainnet binance-elite-9006-mainnet binance-elite-9007-mainnet elite-full-supervisor; do
  if [[ -f "${APP_ROOT}/deploy/${svc}.service" ]]; then
    _install_svc "${svc}.service" "${svc}.service"
  fi
done
sudo systemctl daemon-reload
sudo systemctl enable binance-elite-9005-mainnet binance-elite-9006-mainnet binance-elite-9007-mainnet elite-full-supervisor

if [[ -f "${APP_ROOT}/deploy/logrotate-elite-9005.conf" ]]; then
  sudo cp "${APP_ROOT}/deploy/logrotate-elite-9005.conf" /etc/logrotate.d/elite-full
fi
if [[ -f "${APP_ROOT}/deploy/gcp_backup_cron.sh" ]]; then
  chmod +x "${APP_ROOT}/deploy/gcp_backup_cron.sh"
  (crontab -l 2>/dev/null | grep -v gcp_backup_cron; echo "15 3 * * * GCP_PROJECT=${GCP_PROJECT} GCS_BACKUP_BUCKET=${GCS_BACKUP_BUCKET:-} ${APP_ROOT}/deploy/gcp_backup_cron.sh >> ${APP_ROOT}/logs/backup.log 2>&1") | crontab -
fi
if [[ -f "${APP_ROOT}/deploy/gcp_lab_rag_sync.sh" ]]; then
  chmod +x "${APP_ROOT}/deploy/gcp_lab_rag_sync.sh"
  (crontab -l 2>/dev/null | grep -v gcp_lab_rag_sync; echo "0 4 * * * ${APP_ROOT}/deploy/gcp_lab_rag_sync.sh >> ${APP_ROOT}/logs/lab_rag_sync.log 2>&1") | crontab -
fi

mkdir -p "${APP_ROOT}/logs"

echo ""
echo "Bootstrap tamam."
echo "  .env → ${APP_ROOT}/.env (chmod 600) — veya: bash deploy/gcp_secret_manager.sh pull"
if [[ "${PANEL_MODE}" == "ports" ]]; then
  echo "  Panel (domain yok — statik IP + port):"
  echo "    http://SUNUCU_IP:9085/           → 9005 BERSERK2"
  echo "    http://SUNUCU_IP:9086/paper      → 9006 MEGA"
  echo "    http://SUNUCU_IP:9087/paper      → 9007 desk"
  echo "    http://SUNUCU_IP:9087/admin      → Admin"
  echo "    http://SUNUCU_IP:9087/lab        → Eğitim Lab"
else
  echo "  TLS:"
  echo "    sudo certbot --nginx -d ${PANEL_DOMAIN_9005} -d ${PANEL_DOMAIN_9006} -d ${PANEL_DOMAIN_9007}"
fi
echo "  Başlat:"
echo "    sudo systemctl start binance-elite-9005-mainnet binance-elite-9006-mainnet binance-elite-9007-mainnet elite-full-supervisor"
