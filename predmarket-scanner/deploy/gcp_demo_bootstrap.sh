.çxz< #!/usr/bin/env bash
# Sunucuda TEK KOMUT — Elite 9005 DEMO kurulumu (Ubuntu 22.04)
# Kullanım: cd /opt/binancex/predmarket-scanner && sudo bash deploy/gcp_demo_bootstrap.sh
set -euo pipefail

APP_ROOT="${APP_ROOT:-/opt/binancex/predmarket-scanner}"
APP_USER="${SUDO_USER:-$(logname 2>/dev/null || echo asilsoykan035)}"
PANEL_DOMAIN="${PANEL_DOMAIN:-}"
PANEL_AUTH_USER="${PANEL_AUTH_USER:-elite}"

echo "=============================================="
echo " Elite 9005 DEMO — sunucu kurulumu"
echo " APP_ROOT=${APP_ROOT}"
echo "=============================================="

if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
  echo "HATA: root gerekli. Çalıştır: sudo bash deploy/gcp_demo_bootstrap.sh" >&2
  echo "sudo yetkin yoksa: bash deploy/gcp_demo_user_install.sh" >&2
  echo "Detay: deploy/GCP_SUDO_FIX.md" >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq \
  python3.11 python3.11-venv python3-pip \
  git curl nginx apache2-utils certbot python3-certbot-nginx \
  ufw chrony sqlite3 rsync logrotate

systemctl enable --now chrony

# Swap
if ! swapon --show | grep -q swapfile; then
  fallocate -l 2G /swapfile 2>/dev/null || dd if=/dev/zero of=/swapfile bs=1M count=2048
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  grep -q swapfile /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi
cat > /etc/sysctl.d/99-trading.conf <<'EOF'
vm.swappiness=10
net.core.rmem_max=16777216
net.ipv4.tcp_fastopen=3
EOF
sysctl --system >/dev/null 2>&1 || true

# Firewall — 9005 dışarı kapalı, nginx 80/443 açık
ufw default deny incoming
ufw default allow outgoing
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
echo "y" | ufw enable || true

mkdir -p "${APP_ROOT}/logs" "${APP_ROOT}/data" "${APP_ROOT}/.pids"
chown -R "${APP_USER}:${APP_USER}" /opt/binancex 2>/dev/null || true

if [[ ! -f "${APP_ROOT}/requirements.txt" ]]; then
  echo "HATA: Kod yok. Önce Mac'ten: bash deploy/gcp_upload_from_mac.sh user@SUNUCU_IP" >&2
  exit 1
fi

# Python venv
cd "${APP_ROOT}"
sudo -u "${APP_USER}" python3.11 -m venv .venv
sudo -u "${APP_USER}" .venv/bin/pip install -U pip wheel -q
sudo -u "${APP_USER}" .venv/bin/pip install -r requirements.txt -q
chmod +x run_binance_elite_8300_9005.sh scripts/*.sh deploy/*.sh 2>/dev/null || true

# .env kontrol
if [[ ! -f "${APP_ROOT}/.env" ]]; then
  echo ""
  echo "UYARI: .env yok!"
  echo "  Mac'ten kopyala: scp predmarket-scanner/.env ${APP_USER}@SUNUCU:${APP_ROOT}/.env"
  echo "  chmod 600 .env"
  echo ""
fi
[[ -f "${APP_ROOT}/.env" ]] && chmod 600 "${APP_ROOT}/.env"

# nginx + şifre
mkdir -p /etc/nginx/snippets
if [[ ! -f /etc/nginx/.htpasswd_elite ]]; then
  echo "Panel şifresi belirle (${PANEL_AUTH_USER}):"
  htpasswd -c /etc/nginx/.htpasswd_elite "${PANEL_AUTH_USER}"
fi

cp "${APP_ROOT}/deploy/nginx-elite-9005.conf" /etc/nginx/sites-available/elite-9005
if [[ -n "${PANEL_DOMAIN}" ]]; then
  sed -i "s/panel.example.com/${PANEL_DOMAIN}/g" /etc/nginx/sites-available/elite-9005
else
  cp "${APP_ROOT}/deploy/nginx-elite-9005-http-only.conf" /etc/nginx/sites-available/elite-9005
  echo "Domain yok — HTTP-only (IP ile panel). TLS için: PANEL_DOMAIN=... certbot"
fi
ln -sf /etc/nginx/sites-available/elite-9005 /etc/nginx/sites-enabled/elite-9005
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl enable nginx
systemctl reload nginx

# systemd — DEMO bot
sed "s|/opt/binancex/predmarket-scanner|${APP_ROOT}|g; s|User=ubuntu|User=${APP_USER}|g; s|Group=ubuntu|Group=${APP_USER}|g" \
  "${APP_ROOT}/deploy/binance-elite-9005-demo.service" \
  > /etc/systemd/system/binance-elite-9005-demo.service

sed "s|/opt/binancex/predmarket-scanner|${APP_ROOT}|g; s|User=ubuntu|User=${APP_USER}|g; s|Group=ubuntu|Group=${APP_USER}|g" \
  "${APP_ROOT}/deploy/elite-9005-supervisor.service" \
  > /etc/systemd/system/elite-9005-supervisor.service

# Supervisor demo modu (mainnet değil)
sed -i '/Environment=ELITE_9005_MAINNET=1/d' /etc/systemd/system/elite-9005-supervisor.service || true

systemctl daemon-reload
systemctl enable binance-elite-9005-demo.service elite-9005-supervisor.service

# logrotate + yedek cron
cp "${APP_ROOT}/deploy/logrotate-elite-9005.conf" /etc/logrotate.d/elite-9005 2>/dev/null || true
chmod +x "${APP_ROOT}/deploy/gcp_backup_cron.sh" 2>/dev/null || true

# Botu başlat
systemctl restart binance-elite-9005-demo.service
sleep 5
systemctl start elite-9005-supervisor.service

echo ""
echo "=============================================="
echo " KURULUM TAMAM (DEMO mod)"
echo "=============================================="
echo "  Bot log:  tail -f ${APP_ROOT}/logs/binance_elite_8300_9005.log"
echo "  Durum:    systemctl status binance-elite-9005-demo"
echo "  Panel:    http://$(curl -s ifconfig.me 2>/dev/null || echo SUNUCU_IP)/"
echo "            Kullanıcı: ${PANEL_AUTH_USER} + az önce girdiğin şifre"
echo ""
echo "  Domain varsa TLS:"
echo "    certbot --nginx -d panel.senin-domain.com"
echo ""
echo "  Binance demo API → IP whitelist'e sunucu IP ekle:"
echo "    $(curl -s ifconfig.me 2>/dev/null || echo 'curl ifconfig.me')"
echo "=============================================="
