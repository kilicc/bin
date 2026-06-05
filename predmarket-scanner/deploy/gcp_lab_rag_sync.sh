#!/usr/bin/env bash
# Lab RAG sync — lessons + documents → GCS (Vertex AI Search ingest hazırlığı)
set -euo pipefail

ROOT="${APP_ROOT:-/opt/binancex/predmarket-scanner}"
cd "${ROOT}"

BUCKET="${GCS_BACKUP_BUCKET:-}"
LAB_DIR="data/lab_9007"
STAMP=$(date -u +%Y%m%d)

if [[ ! -d "${LAB_DIR}" ]]; then
  echo "Lab dizini yok: ${LAB_DIR}"
  exit 0
fi

if [[ -z "${BUCKET}" ]]; then
  echo "GCS_BACKUP_BUCKET ayarlanmadı — lab RAG sync atlandı"
  exit 0
fi

if ! command -v gsutil >/dev/null 2>&1; then
  echo "gsutil yok"
  exit 1
fi

DEST="gs://${BUCKET}/lab-rag/${STAMP}/"
gsutil -m rsync -r "${LAB_DIR}/documents" "${DEST}documents/" 2>/dev/null || true
if [[ -f "${LAB_DIR}/lessons.jsonl" ]]; then
  gsutil cp "${LAB_DIR}/lessons.jsonl" "${DEST}lessons.jsonl"
fi
echo "Lab RAG sync: ${DEST}"
echo "Vertex AI Search data store bu prefix'e bağlanabilir (Console → Discovery Engine)."
