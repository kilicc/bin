#!/usr/bin/env bash
# MEGA 9006 — BTC 1m rejim + şelale sıkı takip deploy
set -euo pipefail

PROJECT="${GCP_PROJECT:-project-5f8843cb-1905-4297-af4}"
ZONE="${GCP_ZONE:-asia-northeast1-a}"
INSTANCE="${GCP_INSTANCE:-elite-full-mainnet}"
REMOTE="/opt/binancex/predmarket-scanner"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

FILES=(
  binance_elite_pro.py
  elite_trader/berserk2_btc_context.py
  elite_trader/btc_flash_cascade.py
  elite_trader/btc_macro_feed.py
  elite_trader/btc_liq_feed.py
  elite_trader/mega_direction_guard.py
  elite_trader/mega_live.py
  elite_trader/mega_control.py
  elite_trader/evrim_news_feed.py
  elite_trader/pipeline_alerts.py
  panel/elite_v2/js/paper-dashboard.js
  panel/elite_v2/js/connection-banner.js
  panel/elite_v2/css/paper.css
  panel/elite_v2/paper.html
  scenarios/binance_elite_mega_9006_mainnet.env
)

for f in "${FILES[@]}"; do
  base="$(basename "${f}")"
  gcloud compute scp "${ROOT}/${f}" "${INSTANCE}:/tmp/_${base}" \
    --zone="${ZONE}" --project="${PROJECT}"
done

CMC_KEY=""
FMP_KEY=""
CQ_KEY=""
if [[ -f "${ROOT}/scenarios/.env.mega_9006" ]]; then
  CMC_KEY="$(grep -E '^COINMARKETCAP_API_KEY=' "${ROOT}/scenarios/.env.mega_9006" | cut -d= -f2- | tr -d '"' || true)"
  FMP_KEY="$(grep -E '^FMP_API_KEY=' "${ROOT}/scenarios/.env.mega_9006" | cut -d= -f2- | tr -d '"' || true)"
  CQ_KEY="$(grep -E '^CRYPTOQUANT_API_KEY=' "${ROOT}/scenarios/.env.mega_9006" | cut -d= -f2- | tr -d '"' || true)"
fi

gcloud compute ssh "${INSTANCE}" --zone="${ZONE}" --project="${PROJECT}" --command="
set -e
cd ${REMOTE}
sudo cp /tmp/_binance_elite_pro.py binance_elite_pro.py
sudo cp /tmp/_berserk2_btc_context.py elite_trader/berserk2_btc_context.py
sudo cp /tmp/_btc_flash_cascade.py elite_trader/btc_flash_cascade.py
sudo cp /tmp/_btc_macro_feed.py elite_trader/btc_macro_feed.py
sudo cp /tmp/_btc_liq_feed.py elite_trader/btc_liq_feed.py
sudo cp /tmp/_mega_direction_guard.py elite_trader/mega_direction_guard.py
sudo cp /tmp/_evrim_news_feed.py elite_trader/evrim_news_feed.py
sudo cp /tmp/_mega_live.py elite_trader/mega_live.py
sudo cp /tmp/_mega_control.py elite_trader/mega_control.py
sudo cp /tmp/_pipeline_alerts.py elite_trader/pipeline_alerts.py
sudo cp /tmp/_paper-dashboard.js panel/elite_v2/js/paper-dashboard.js
sudo cp /tmp/_connection-banner.js panel/elite_v2/js/connection-banner.js
sudo cp /tmp/_paper.css panel/elite_v2/css/paper.css
sudo cp /tmp/_paper.html panel/elite_v2/paper.html
sudo cp /tmp/_binance_elite_mega_9006_mainnet.env scenarios/binance_elite_mega_9006_mainnet.env
sudo touch scenarios/.env.mega_9006
if [[ -n '${CMC_KEY}' ]] && ! sudo grep -q '^COINMARKETCAP_API_KEY=' scenarios/.env.mega_9006 2>/dev/null; then
  echo 'COINMARKETCAP_API_KEY=${CMC_KEY}' | sudo tee -a scenarios/.env.mega_9006 >/dev/null
fi
if [[ -n '${FMP_KEY}' ]] && ! sudo grep -q '^FMP_API_KEY=' scenarios/.env.mega_9006 2>/dev/null; then
  echo 'FMP_API_KEY=${FMP_KEY}' | sudo tee -a scenarios/.env.mega_9006 >/dev/null
fi
if [[ -n '${CQ_KEY}' ]] && ! sudo grep -q '^CRYPTOQUANT_API_KEY=' scenarios/.env.mega_9006 2>/dev/null; then
  echo 'CRYPTOQUANT_API_KEY=${CQ_KEY}' | sudo tee -a scenarios/.env.mega_9006 >/dev/null
fi
sudo chown -R pro:pro elite_trader panel scenarios 2>/dev/null || true
echo '=== restart 9006 ==='
sudo systemctl restart binance-elite-9006-mainnet
sleep 40
python3 <<'PY'
import json, urllib.request
for path in ('/api/status', '/api/scan/summary'):
    try:
        d = json.load(urllib.request.urlopen('http://127.0.0.1:9006'+path, timeout=30))
        if 'scan' in path or 'summary' in str(d):
            sc = d if isinstance(d, dict) else {}
            btc = sc.get('btc_context') or {}
            casc = btc.get('btc_cascade') or {}
            print('btc_regime', btc.get('regime_label'), 'cascade', casc.get('phase_label'))
        else:
            print('status', 'live_orders', d.get('live_orders'), 'control', (d.get('mega_control') or {}).get('state'))
    except Exception as e:
        print(path, 'ERR', e)
PY
systemctl is-active binance-elite-9006-mainnet
"

echo "gcp_9006_btc_tight tamam."
