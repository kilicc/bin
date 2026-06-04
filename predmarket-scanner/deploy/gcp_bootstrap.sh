#!/usr/bin/env bash
# GCP VM ilk kurulum — Ubuntu 22.04 üzerinde Elite 9005 mainnet
set -euo pipefail

APP_ROOT="${APP_ROOT:-/opt/binancex/predmarket-scanner}"
APP_USER="${APP_USER:-$(whoami)}"
PANEL_DOMAIN="${PANEL_DOMAIN:-}"
PANEL_AUTH_USER="${PANEL_AUTH_USER:-elite}"

echo "=== Elite 9005 GCP bootstrap ==="
echo "APP_ROOT=${APP_ROOT}"

export DEBIAN_FRONTEND=noninteractive
sudo apt-get update -qq
sudo apt-get install -y -qq \
  python3.11 python3.11-venv python3-pip \
  git curl nginx apache2-utils certbot python3-certbot-nginx \
  ufw chrony sqlite3 rsync logrotate

# NTP
sudo systemctl enable --now chrony

# Swap (OOM sigortası)
if ! swapon --show | grep -q swapfile; then
  sudo fallocate -l 2G /swapfile || sudo dd if=/dev/zero of=/swapfile bs=1M count=2048
  sudo chmod 600 /swapfile
  sudo mkswap /swapfile
  sudo swapon /swapfile
  grep -q swapfile /etc/fstab || echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
  echo 'vm.swappiness=10' | sudo tee /etc/sysctl.d/99-trading.conf
  echo 'net.core.rmem_max = 16777216' | sudo tee -a /etc/sysctl.d/99-trading.conf
  echo 'net.ipv4.tcp_fastopen = 3' | sudo tee -a /etc/sysctl.d/99-trading.conf
  sudo sysctl --system
fi

# Firewall
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
echo "y" | sudo ufw enable || true

# Data disk mount (startup script sonrası)
DATA_MNT="/opt/binancex/data"
sudo mkdir -p "${DATA_MNT}" "${APP_ROOT}"
if mountpoint -q "${DATA_MNT}" 2>/dev/null; then
  echo "Veri diski mount OK: ${DATA_MNT}"
  if [[ -d "${APP_ROOT}/data" ]] && [[ ! -L "${APP_ROOT}/data" ]]; then
    if [[ -z "$(ls -A "${APP_ROOT}/data" 2>/dev/null)" ]]; then
      rmdir "${APP_ROOT}/data" 2>/dev/null || true
    fi
  fi
  if [[ ! -e "${APP_ROOT}/data" ]]; then
    ln -sfn "${DATA_MNT}" "${APP_ROOT}/data"
  fi
fi

# Python venv (kod rsync sonrası tamamlanır)
if [[ -f "${APP_ROOT}/requirements.txt" ]]; then
  cd "${APP_ROOT}"
  python3.11 -m venv .venv
  .venv/bin/pip install -U pip wheel
  .venv/bin/pip install -r requirements.txt
  chmod +x run_binance_elite_9005_mainnet.sh scripts/*.sh deploy/*.sh 2>/dev/null || true
fi

# nginx + basic auth
sudo mkdir -p /etc/nginx/snippets
if [[ ! -f /etc/nginx/.htpasswd_elite ]]; then
  echo "Panel şifresi oluşturuluyor (${PANEL_AUTH_USER})..."
  sudo htpasswd -c /etc/nginx/.htpasswd_elite "${PANEL_AUTH_USER}"
fi

if [[ -f "${APP_ROOT}/deploy/nginx-elite-9005.conf" ]]; then
  sudo cp "${APP_ROOT}/deploy/nginx-elite-9005.conf" /etc/nginx/sites-available/elite-9005
  sudo ln -sf /etc/nginx/sites-available/elite-9005 /etc/nginx/sites-enabled/elite-9005
  sudo rm -f /etc/nginx/sites-enabled/default
  if [[ -n "${PANEL_DOMAIN}" ]]; then
    sudo sed -i "s/panel.example.com/${PANEL_DOMAIN}/g" /etc/nginx/sites-available/elite-9005
  fi
  sudo nginx -t
  sudo systemctl enable nginx
  sudo systemctl reload nginx
fi

# systemd
if [[ -f "${APP_ROOT}/deploy/binance-elite-9005-mainnet.service" ]]; then
  sudo sed "s|/opt/binancex/predmarket-scanner|${APP_ROOT}|g; s|User=.*|User=${APP_USER}|g; s|Group=.*|Group=${APP_USER}|g" \
    "${APP_ROOT}/deploy/binance-elite-9005-mainnet.service" \
    | sudo tee /etc/systemd/system/binance-elite-9005-mainnet.service >/dev/null
  sudo sed "s|/opt/binancex/predmarket-scanner|${APP_ROOT}|g; s|User=.*|User=${APP_USER}|g; s|Group=.*|Group=${APP_USER}|g" \
    "${APP_ROOT}/deploy/elite-9005-supervisor.service" \
    | sudo tee /etc/systemd/system/elite-9005-supervisor.service >/dev/null
  sudo systemctl daemon-reload
  sudo systemctl enable binance-elite-9005-mainnet.service elite-9005-supervisor.service
fi

# logrotate + backup cron
if [[ -f "${APP_ROOT}/deploy/logrotate-elite-9005.conf" ]]; then
  sudo cp "${APP_ROOT}/deploy/logrotate-elite-9005.conf" /etc/logrotate.d/elite-9005
fi
if [[ -f "${APP_ROOT}/deploy/gcp_backup_cron.sh" ]]; then
  chmod +x "${APP_ROOT}/deploy/gcp_backup_cron.sh"
  (crontab -l 2>/dev/null | grep -v gcp_backup_cron; echo "15 3 * * * ${APP_ROOT}/deploy/gcp_backup_cron.sh >> ${APP_ROOT}/logs/backup.log 2>&1") | crontab -
fi

echo ""
echo "Bootstrap tamam."
echo "  .env kopyala → ${APP_ROOT}/.env (chmod 600)"
echo "  TLS: sudo certbot --nginx -d ${PANEL_DOMAIN:-panel.example.com}"
echo "  Başlat: sudo systemctl start binance-elite-9005-mainnet elite-9005-supervisor"
