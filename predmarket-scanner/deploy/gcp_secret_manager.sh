#!/usr/bin/env bash
# Secret Manager — .env push/pull (GCP sunucu veya Mac)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PROJECT="${GCP_PROJECT:-}"
SECRET_NAME="${GCP_ENV_SECRET:-binancex-elite-env}"
ENV_FILE="${ENV_FILE:-${ROOT}/.env}"
ACTION="${1:-pull}"

if [[ -z "${PROJECT}" ]]; then
  PROJECT=$(gcloud config get-value project 2>/dev/null || true)
fi
if [[ -z "${PROJECT}" || "${PROJECT}" == "(unset)" ]]; then
  echo "GCP_PROJECT ayarlayın" >&2
  exit 1
fi

case "${ACTION}" in
  push)
    if [[ ! -f "${ENV_FILE}" ]]; then
      echo ".env bulunamadı: ${ENV_FILE}" >&2
      exit 1
    fi
    if gcloud secrets describe "${SECRET_NAME}" --project="${PROJECT}" &>/dev/null; then
      gcloud secrets versions add "${SECRET_NAME}" --project="${PROJECT}" --data-file="${ENV_FILE}"
    else
      gcloud secrets create "${SECRET_NAME}" --project="${PROJECT}" --replication-policy=automatic --data-file="${ENV_FILE}"
    fi
    echo "Secret güncellendi: ${SECRET_NAME}"
    ;;
  pull)
    gcloud secrets versions access latest --secret="${SECRET_NAME}" --project="${PROJECT}" >"${ENV_FILE}.tmp"
    chmod 600 "${ENV_FILE}.tmp"
    mv "${ENV_FILE}.tmp" "${ENV_FILE}"
    echo ".env çekildi: ${ENV_FILE} (chmod 600)"
    ;;
  *)
    echo "Kullanım: $0 {push|pull}" >&2
    exit 1
    ;;
esac
