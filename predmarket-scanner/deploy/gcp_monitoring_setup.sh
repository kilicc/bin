#!/usr/bin/env bash
# Cloud Monitoring uptime checks — 3 panel subdomain
set -euo pipefail

PROJECT="${GCP_PROJECT:-}"
PANEL_DOMAIN_9005="${PANEL_DOMAIN_9005:-9005.example.com}"
PANEL_DOMAIN_9006="${PANEL_DOMAIN_9006:-mega6.example.com}"
PANEL_DOMAIN_9007="${PANEL_DOMAIN_9007:-mega7.example.com}"

if [[ -z "${PROJECT}" ]]; then
  PROJECT=$(gcloud config get-value project 2>/dev/null || true)
fi
if [[ -z "${PROJECT}" || "${PROJECT}" == "(unset)" ]]; then
  echo "GCP_PROJECT ayarlayın" >&2
  exit 1
fi

_create_check() {
  local name="$1" host="$2" path="$3"
  if gcloud monitoring uptime list-configs --project="${PROJECT}" --filter="displayName=${name}" --format='value(name)' 2>/dev/null | grep -q .; then
    echo "Uptime check mevcut: ${name}"
    return 0
  fi
  gcloud monitoring uptime create "${name}" \
    --project="${PROJECT}" \
    --resource-type=uptime-url \
    --host="${host}" \
    --path="${path}" \
    --port=443 \
    --use-ssl \
    --period=60 \
    --timeout=10 \
    --quiet 2>/dev/null || echo "Uptime check oluşturulamadı (Console'dan manuel ekleyin): ${name} → https://${host}${path}"
}

_create_check "elite-9005-panel" "${PANEL_DOMAIN_9005}" "/api/heartbeat"
_create_check "elite-9006-mega" "${PANEL_DOMAIN_9006}" "/api/paper/mega/snapshot?light=1"
_create_check "elite-9007-lab" "${PANEL_DOMAIN_9007}" "/api/health/strip"

echo ""
echo "Cloud Monitoring → Uptime checks bölümünden alert policy ekleyin (email/SMS)."
