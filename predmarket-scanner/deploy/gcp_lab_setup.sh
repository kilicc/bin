#!/usr/bin/env bash
# Sunucuda lab bilgi bootstrap + Vertex doğrulama
set -euo pipefail

PROJECT="${GCP_PROJECT:-project-5f8843cb-1905-4297-af4}"
ZONE="${GCP_ZONE:-asia-northeast1-a}"
INSTANCE="${GCP_INSTANCE:-elite-full-mainnet}"
REMOTE="/opt/binancex/predmarket-scanner"

gcloud compute ssh "${INSTANCE}" --zone="${ZONE}" --project="${PROJECT}" --command="
set -e
cd ${REMOTE}
source .venv/bin/activate
export MEGA_INSTANCE_ID=9007
python scripts/lab_bootstrap_knowledge.py --json
python -c \"
import os
from dotenv import load_dotenv
load_dotenv('.env')
from elite_trader.training_lab.llm_client import chat
r = chat([{'role':'user','content':'ping'}])
print('vertex_ok', r.get('ok'), r.get('provider'), r.get('error'))
\"
sudo systemctl restart binance-elite-9007-mainnet
sudo systemctl start elite-full-supervisor
systemctl is-active binance-elite-9007-mainnet elite-full-supervisor
"

echo "Lab setup tamam."
