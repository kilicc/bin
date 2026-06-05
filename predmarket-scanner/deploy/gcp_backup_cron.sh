#!/usr/bin/env bash
# Günlük yedek — 9005 + 9006/9007 + Lab → GCS (GCP sunucuda cron)
set -euo pipefail

ROOT="${APP_ROOT:-/opt/binancex/predmarket-scanner}"
cd "${ROOT}"
mkdir -p logs backups/daily

TS=$(date -u +%Y%m%dT%H%M%SZ)
STAMP=$(date -u +%Y%m%d)
BUCKET="${GCS_BACKUP_BUCKET:-}"
PROJECT="${GCP_PROJECT:-}"

DB="data/binance_elite_8300_9005_state.db"
if [[ -f "${DB}" ]]; then
  sqlite3 "${DB}" ".backup 'backups/daily/state_${TS}.db'"
  echo "DB backup: backups/daily/state_${TS}.db"
fi

tar -czf "backups/daily/elite9005_data_${STAMP}.tar.gz" \
  data/elite_9005_trade_lessons.json \
  data/elite_9005_learning_registry.json \
  data/elite_9005_proposals.json \
  data/elite_sl_emergency_registry.json \
  data/elite_9005_loss_postmortem.json \
  data/deleted_archives/manifest.json \
  2>/dev/null || true

if [[ -d data/mega_9007 ]]; then
  tar -czf "backups/daily/mega9007_${STAMP}.tar.gz" data/mega_9007/ 2>/dev/null || true
fi
if [[ -d data/lab_9007 ]]; then
  tar -czf "backups/daily/lab9007_${STAMP}.tar.gz" data/lab_9007/ 2>/dev/null || true
fi

find backups/daily -type f -mtime +14 -delete 2>/dev/null || true

if [[ -z "${BUCKET}" ]]; then
  echo "FAIL: GCS_BACKUP_BUCKET zorunlu (export GCS_BACKUP_BUCKET=your-bucket)" >&2
  exit 1
fi

if ! command -v gsutil >/dev/null 2>&1; then
  echo "FAIL: gsutil yok — google-cloud-cli kurun" >&2
  exit 1
fi

DEST="gs://${BUCKET}/elite-full/${STAMP}/"
gsutil -m cp backups/daily/*_${STAMP}* "${DEST}" 2>/dev/null || \
  gsutil -m cp backups/daily/state_${TS}.db "${DEST}" || true
echo "GCS upload: ${DEST}"
