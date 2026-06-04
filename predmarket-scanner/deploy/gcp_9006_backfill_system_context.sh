#!/usr/bin/env bash
# MEGA 9006 — retro system context (kapalı + arşiv + audit)
set -euo pipefail

PROJECT="${GCP_PROJECT:-project-5f8843cb-1905-4297-af4}"
ZONE="${GCP_ZONE:-asia-northeast1-a}"
INSTANCE="${GCP_INSTANCE:-elite-full-mainnet}"
REMOTE="/opt/binancex/predmarket-scanner"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

for f in elite_trader/mega_system_context_backfill.py scripts/backfill_mega_system_context.py; do
  base="$(basename "${f}")"
  gcloud compute scp "${ROOT}/${f}" "${INSTANCE}:/tmp/_${base}" \
    --zone="${ZONE}" --project="${PROJECT}"
done

gcloud compute ssh "${INSTANCE}" --zone="${ZONE}" --project="${PROJECT}" --command="
set -e
cd ${REMOTE}
sudo cp /tmp/_mega_system_context_backfill.py elite_trader/mega_system_context_backfill.py
sudo cp /tmp/_backfill_mega_system_context.py scripts/backfill_mega_system_context.py
sudo chown pro:pro elite_trader scripts/backfill_mega_system_context.py
export MEGA_INSTANCE_ID=9006
python3 scripts/backfill_mega_system_context.py --instance 9006 --include-archives \
  --consolidate-out mega_live_closed_history.json --audit
wc -l data/mega_9006/mega_close_audit.jsonl
python3 -c \"
import json
from pathlib import Path
h=Path('data/mega_9006/mega_live_closed_history.json')
c=Path('data/mega_9006/mega_live_closed.json')
for p in (h,c):
    if not p.is_file():
        print(p.name,'missing')
        continue
    d=json.loads(p.read_text())
    rows=d.get('closed') or []
    ec=sum(1 for r in rows if r.get('entry_context'))
    print(p.name,'trades',len(rows),'with_entry_context',ec)
\"
"

echo "gcp_9006_backfill_system_context tamam."
