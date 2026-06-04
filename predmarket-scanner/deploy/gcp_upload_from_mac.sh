#!/usr/bin/env bash
# Mac'ten sunucuya kod + data yükle (rsync sunucuda olmasa da çalışır)
set -euo pipefail

REMOTE="${1:-}"
if [[ -z "${REMOTE}" ]]; then
  echo "Kullanım: bash deploy/gcp_upload_from_mac.sh KULLANICI@SUNUCU_IP"
  echo ""
  echo "Örnek: bash deploy/gcp_upload_from_mac.sh asilsoykan035@34.104.243.96"
  echo ""
  echo "Passphrase'li key: önce  ssh-add ~/.ssh/id_ed25519"
  exit 1
fi

SSH_IDENTITY="${SSH_IDENTITY:-$HOME/.ssh/id_ed25519}"
if [[ ! -f "${SSH_IDENTITY}" ]]; then
  echo "HATA: SSH key yok: ${SSH_IDENTITY}" >&2
  echo "  SSH_IDENTITY=~/.ssh/id_ed25519_gcp bash deploy/gcp_upload_from_mac.sh ..." >&2
  exit 1
fi

SSH_BASE=(ssh -o IdentitiesOnly=yes -o IdentityFile="${SSH_IDENTITY}" -o ConnectTimeout=15)
SCP_BASE=(scp -o IdentitiesOnly=yes -o IdentityFile="${SSH_IDENTITY}" -o ConnectTimeout=15)
RSYNC_SSH="ssh -o IdentitiesOnly=yes -o IdentityFile=${SSH_IDENTITY}"

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/.."

REMOTE_DIR="/opt/binancex/predmarket-scanner"

echo "=== SSH test → ${REMOTE} (key: ${SSH_IDENTITY}) ==="
if ! "${SSH_BASE[@]}" -o BatchMode=yes "${REMOTE}" "echo ok" 2>/dev/null; then
  echo ""
  echo "SSH bağlanamadı (publickey)." >&2
  echo "  1) Key sunucuda mı? GCP Metadata veya authorized_keys" >&2
  echo "  2) Passphrase:  eval \"\$(ssh-agent -s)\" && ssh-add ${SSH_IDENTITY}" >&2
  echo "  3) Manuel test: ssh -i ${SSH_IDENTITY} ${REMOTE}" >&2
  exit 1
fi

echo "=== Sunucu hazırlığı ==="
"${SSH_BASE[@]}" "${REMOTE}" "sudo mkdir -p /opt/binancex && sudo chown \$(whoami):\$(whoami) /opt/binancex && mkdir -p ${REMOTE_DIR}"

USE_RSYNC=0
if "${SSH_BASE[@]}" "${REMOTE}" "command -v rsync >/dev/null 2>&1"; then
  USE_RSYNC=1
else
  echo "  Sunucuda rsync yok — tar ile yüklenecek"
  if "${SSH_BASE[@]}" "${REMOTE}" "sudo apt-get update -qq && sudo apt-get install -y -qq rsync" 2>/dev/null; then
    if "${SSH_BASE[@]}" "${REMOTE}" "command -v rsync >/dev/null 2>&1"; then
      USE_RSYNC=1
      echo "  rsync kuruldu."
    fi
  fi
fi

echo "=== Kod yükleniyor → ${REMOTE}:${REMOTE_DIR} ==="
if [[ "${USE_RSYNC}" == "1" ]]; then
  rsync -avz --progress -e "${RSYNC_SSH}" \
    --exclude '.venv/' \
    --exclude '__pycache__/' \
    --exclude '*.pyc' \
    --exclude '.git/' \
    --exclude 'logs/' \
    --exclude '.pids/' \
    --exclude 'data/backups/' \
    --exclude 'node_modules/' \
    predmarket-scanner/ "${REMOTE}:${REMOTE_DIR}/"
else
  tar czf - \
    --exclude='predmarket-scanner/.venv' \
    --exclude='predmarket-scanner/__pycache__' \
    --exclude='predmarket-scanner/.git' \
    --exclude='predmarket-scanner/logs' \
    --exclude='predmarket-scanner/.pids' \
    --exclude='predmarket-scanner/data/backups' \
    --exclude='predmarket-scanner/node_modules' \
    predmarket-scanner \
    | "${SSH_BASE[@]}" "${REMOTE}" "tar xzf - -C /opt/binancex"
fi

echo ""
echo "=== .env ==="
if [[ -f predmarket-scanner/.env ]]; then
  "${SCP_BASE[@]}" -q predmarket-scanner/.env "${REMOTE}:${REMOTE_DIR}/.env"
  "${SSH_BASE[@]}" "${REMOTE}" "chmod 600 ${REMOTE_DIR}/.env"
  echo "  .env yüklendi"
else
  echo "  UYARI: .env yok"
fi

echo ""
echo "=== data/ ==="
if [[ -d predmarket-scanner/data ]]; then
  "${SSH_BASE[@]}" "${REMOTE}" "mkdir -p ${REMOTE_DIR}/data"
  if [[ "${USE_RSYNC}" == "1" ]]; then
    rsync -avz --progress -e "${RSYNC_SSH}" \
      predmarket-scanner/data/ \
      "${REMOTE}:${REMOTE_DIR}/data/" \
      --exclude 'backups/'
  else
    tar czf - -C predmarket-scanner data \
      | "${SSH_BASE[@]}" "${REMOTE}" "tar xzf - -C ${REMOTE_DIR}"
  fi
  echo "  data/ yüklendi"
fi

echo ""
echo "=== Tamam ==="
echo "  ssh -i ${SSH_IDENTITY} ${REMOTE}"
echo "  cd ${REMOTE_DIR} && sudo bash deploy/gcp_demo_bootstrap.sh"
