#!/usr/bin/env bash
# REST rate-limit koruması — yalnızca 9007 canlı emir; 9005/9006 paper REST kapalı
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

for pf in \
  panel/elite_v2/paper.html \
  panel/elite_v2/index.html \
  panel/elite_v2/css/paper.css \
  panel/elite_v2/css/dashboard.css \
  panel/elite_v2/js/connection-banner.js; do
  gcloud compute scp "${ROOT}/${pf}" "${INSTANCE}:/tmp/$(basename "${pf}")" \
    --zone="${ZONE}" --project="${PROJECT}" 2>/dev/null || true
done

gcloud compute scp \
  "${ROOT}/elite_trader/network_guard.py" \
  "${ROOT}/elite_trader/mega_live.py" \
  "${ROOT}/elite_trader/pipeline_alerts.py" \
  "${ROOT}/elite_trader/paper_book.py" \
  "${ROOT}/elite_trader/parallel_universe_engine.py" \
  "${ROOT}/elite_trader/mega_async_hub.py" \
  "${ROOT}/elite_trader/mega_close_sync.py" \
  "${ROOT}/elite_trader/binance_data_hub.py" \
  "${ROOT}/elite_trader/binance_rest_budget.py" \
  "${ROOT}/elite_trader/connection_alerts.py" \
  "${ROOT}/elite_trader/exchange_trade_truth.py" \
  "${ROOT}/elite_trader/exchange_fill_truth.py" \
  "${ROOT}/elite_trader/fee_economics.py" \
  "${INSTANCE}:${REMOTE}/elite_trader/" \
  --zone="${ZONE}" --project="${PROJECT}"

gcloud compute scp \
  "${ROOT}/binance_futures_trader/fast_price_ws.py" \
  "${INSTANCE}:${REMOTE}/binance_futures_trader/fast_price_ws.py" \
  --zone="${ZONE}" --project="${PROJECT}"

gcloud compute scp \
  "${ROOT}/scenarios/binance_elite_mega_9006_mainnet.env" \
  "${INSTANCE}:${REMOTE}/scenarios/binance_elite_mega_9006_mainnet.env" \
  --zone="${ZONE}" --project="${PROJECT}"

gcloud compute scp \
  "${ROOT}/scenarios/binance_elite_mega_9007_mainnet.env" \
  "${INSTANCE}:${REMOTE}/scenarios/binance_elite_mega_9007_mainnet.env" \
  --zone="${ZONE}" --project="${PROJECT}"

gcloud compute ssh "${INSTANCE}" --zone="${ZONE}" --project="${PROJECT}" --command="
set -e
cd ${REMOTE}
sudo cp -f /tmp/_panel_paper.html panel/elite_v2/paper.html 2>/dev/null || true
sudo cp -f /tmp/_panel_index.html panel/elite_v2/index.html 2>/dev/null || true
sudo cp -f /tmp/_panel_paper.css panel/elite_v2/css/paper.css 2>/dev/null || true
sudo cp -f /tmp/_panel_dashboard.css panel/elite_v2/css/dashboard.css 2>/dev/null || true
sudo cp -f /tmp/_panel_connection-banner.js panel/elite_v2/js/connection-banner.js 2>/dev/null || true
echo '=== Restart (9005/9006 paper REST off, 9007 throttled) ==='
sudo systemctl restart binance-elite-9005-mainnet binance-elite-9006-mainnet binance-elite-9007-mainnet
sleep 40
python3 <<'PY'
import json, urllib.request
for port in (9005, 9006, 9007):
    c = json.load(urllib.request.urlopen(f'http://127.0.0.1:{port}/api/connection/live', timeout=20))
    a = json.load(urllib.request.urlopen(f'http://127.0.0.1:{port}/api/connection/alerts', timeout=20))
    ban = [x for x in a.get('alerts',[]) if x.get('code')=='ip_ban']
    mw = c.get('mark_ws') or {}
    pl = a.get('pipeline') or {}
    bt = c.get('bookticker') or {}
    print(f'P{port} sev={a.get(\"severity\")} book={bt.get(\"ok\")} lag={bt.get(\"lag_ms\")}ms coins={bt.get(\"coins\")} mark={mw.get(\"health\")} lag={mw.get(\"lag_ms\")}')
PY
systemctl is-active binance-elite-9005-mainnet binance-elite-9006-mainnet binance-elite-9007-mainnet
"

echo "gcp_rate_limit_fix tamam."
