#!/usr/bin/env bash
# 9005/9006 paper sıfırla + yeni cüzdan/stake/slot senaryosu + restart (9007 dokunulmaz)
set -euo pipefail

PROJECT="${GCP_PROJECT:-project-5f8843cb-1905-4297-af4}"
ZONE="${GCP_ZONE:-asia-northeast1-a}"
INSTANCE="${GCP_INSTANCE:-elite-full-mainnet}"
REMOTE="/opt/binancex/predmarket-scanner"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REASON="${RESET_REASON:-user_fresh_paper_9005_9006}"

gcloud compute scp \
  "${ROOT}/scripts/reset_paper_9005_9006.py" \
  "${ROOT}/binance_elite_pro.py" \
  "${INSTANCE}:${REMOTE}/" \
  --zone="${ZONE}" --project="${PROJECT}"

gcloud compute scp \
  "${ROOT}/scripts/reset_paper_9005_9006.py" \
  "${INSTANCE}:${REMOTE}/scripts/" \
  --zone="${ZONE}" --project="${PROJECT}"

gcloud compute scp \
  "${ROOT}/scenarios/binance_elite_8300_9005_mainnet.env" \
  "${ROOT}/scenarios/binance_elite_mega_9006_mainnet.env" \
  "${INSTANCE}:${REMOTE}/scenarios/" \
  --zone="${ZONE}" --project="${PROJECT}"

gcloud compute ssh "${INSTANCE}" --zone="${ZONE}" --project="${PROJECT}" --command="
set -e
cd ${REMOTE}
sudo chown -R pro:pro data logs scripts scenarios 2>/dev/null || true

echo '=== Durdur 9005/9006 (paper reset) ==='
sudo systemctl stop binance-elite-9005-mainnet binance-elite-9006-mainnet

echo '=== Paper kitap sıfırla ==='
python3 scripts/reset_paper_9005_9006.py --yes --reason '${REASON}'

echo '=== Restart 9005/9006 ==='
sudo systemctl restart binance-elite-9005-mainnet binance-elite-9006-mainnet
sleep 30

python3 <<'PY'
import json, urllib.request
for port, mode in ((9005, 'berserk2'), (9006, 'mega')):
    snap = json.load(urllib.request.urlopen(f'http://127.0.0.1:{port}/api/paper/{mode}/snapshot', timeout=25))
    book = snap.get('book') or snap
    print(
        f'P{port} {mode} session_start={book.get(\"session_start\")} '
        f'open={len(book.get(\"open\") or [])} closed={len(book.get(\"closed\") or [])}'
    )
    conn = json.load(urllib.request.urlopen(f'http://127.0.0.1:{port}/api/connection/live', timeout=20))
    print(f'  paper={conn.get(\"api_paper\")} opens={conn.get(\"open_positions\")}')
PY
systemctl is-active binance-elite-9005-mainnet binance-elite-9006-mainnet
"

echo "gcp_reset_paper_9005_9006 tamam."
