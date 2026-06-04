#!/usr/bin/env bash
# Mac → GCP kod senkronizasyonu (secrets hariç — .env ayrı kopyalanır)
set -euo pipefail

REMOTE="${1:-}"
if [[ -z "${REMOTE}" ]]; then
  echo "Kullanım: $0 user@GCP_IP" >&2
  exit 1
fi

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/.."

rsync -avz --progress \
  --exclude '.venv/' \
  --exclude '__pycache__/' \
  --exclude '*.pyc' \
  --exclude '.git/' \
  --exclude 'logs/' \
  --exclude '.pids/' \
  --exclude 'data/backups/' \
  --exclude 'node_modules/' \
  predmarket-scanner/ "${REMOTE}:/opt/binancex/predmarket-scanner/"

echo "Kod senkron OK. Sunucuda: cd /opt/binancex/predmarket-scanner && bash deploy/gcp_bootstrap.sh"
