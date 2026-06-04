#!/usr/bin/env bash
# 9007: REST ban azaltma + canlı log yolu + Vertex GCP_PROJECT (metadata)
set -euo pipefail

PROJECT="${GCP_PROJECT:-project-5f8843cb-1905-4297-af4}"
ZONE="${GCP_ZONE:-asia-northeast1-a}"
INSTANCE="${GCP_INSTANCE:-elite-full-mainnet}"
REMOTE="/opt/binancex/predmarket-scanner"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

gcloud compute scp \
  "${ROOT}/binance_elite_pro.py" \
  "${INSTANCE}:${REMOTE}/binance_elite_pro.py" \
  --zone="${ZONE}" --project="${PROJECT}"

gcloud compute scp \
  "${ROOT}/elite_trader/mega_live.py" \
  "${ROOT}/elite_trader/connection_alerts.py" \
  "${INSTANCE}:${REMOTE}/elite_trader/" \
  --zone="${ZONE}" --project="${PROJECT}"

gcloud compute scp \
  "${ROOT}/elite_trader/training_lab/llm_client.py" \
  "${ROOT}/elite_trader/training_lab/ops_monitor.py" \
  "${INSTANCE}:${REMOTE}/elite_trader/training_lab/" \
  --zone="${ZONE}" --project="${PROJECT}"

gcloud compute scp \
  "${ROOT}/scenarios/binance_elite_mega_9007_mainnet.env" \
  "${INSTANCE}:${REMOTE}/scenarios/binance_elite_mega_9007_mainnet.env" \
  --zone="${ZONE}" --project="${PROJECT}"

gcloud compute ssh "${INSTANCE}" --zone="${ZONE}" --project="${PROJECT}" --command="
set -e
cd ${REMOTE}
grep -q '^GCP_PROJECT=' .env 2>/dev/null || echo 'GCP_PROJECT=${PROJECT}' >> .env
sudo systemctl restart binance-elite-9007-mainnet
sleep 28
./.venv/bin/python3 <<'PY'
import json, urllib.request
from elite_trader.training_lab.llm_client import gcp_project_resolved
print('GCP_PROJECT resolved', gcp_project_resolved())
log = json.load(urllib.request.urlopen('http://127.0.0.1:9007/api/logs/process?tail=5', timeout=15))
print('live log ok', log.get('ok'), 'path', log.get('path'), 'lines', len(log.get('lines') or []))
ops = json.load(urllib.request.urlopen('http://127.0.0.1:9007/api/ops/dashboard', timeout=20))
llm = ops.get('llm') or {}
print('LLM primary', (llm.get('primary') or {}).get('ok'), (llm.get('primary') or {}).get('error'))
print('LLM fallback', llm.get('fallback'))
al = json.load(urllib.request.urlopen('http://127.0.0.1:9007/api/connection/alerts', timeout=15))
print('alerts', [a.get('code') for a in al.get('alerts') or []])
PY
"

echo "gcp_fix_ban_ai_logs tamam."
