#!/usr/bin/env bash
# demo-fapi.binance.com erişim testi (9005 canlı emir için gerekli)
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${PY:-./.venv/bin/python}"
if cert="$("$PY" -c "import certifi; print(certifi.where())" 2>/dev/null)"; then
  export SSL_CERT_FILE="$cert"
  export REQUESTS_CA_BUNDLE="$cert"
fi
echo "Ping demo-fapi (15sn timeout)..."
if curl -sS --max-time 15 "https://demo-fapi.binance.com/fapi/v1/ping"; then
  echo ""
  echo "OK — ağ erişimi var. ./run_binance_elite_8300_9005.sh ile 9005'i yeniden başlatın."
else
  echo ""
  echo "HATA — demo-fapi'ye ulaşılamıyor (SSL timeout / firewall / ISP)."
  echo "  • VPN veya farklı ağ deneyin"
  echo "  • Proxy: export HTTPS_PROXY=http://127.0.0.1:PORT sonra yeniden başlatın"
  exit 1
fi
