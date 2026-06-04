#!/usr/bin/env bash
# Binance + panel gecikme ölçümü (Mac veya GCP)
set -euo pipefail

echo "=== Binance REST latency ==="
for host in fapi.binance.com demo-fapi.binance.com; do
  curl -o /dev/null -s -w "${host} connect=%{time_connect}s ttfb=%{time_starttransfer}s total=%{time_total}s\n" \
    "https://${host}/fapi/v1/ping" || echo "${host} FAIL"
done

echo ""
echo "=== Local bot API (varsa) ==="
PORT="${ELITE_9005_PORT:-9005}"
if curl -sf -m 3 "http://127.0.0.1:${PORT}/api/connection/live" >/dev/null 2>&1; then
  curl -o /dev/null -s -w "127.0.0.1:${PORT}/api/live ttfb=%{time_starttransfer}s total=%{time_total}s\n" \
    "http://127.0.0.1:${PORT}/api/live?light=1"
else
  echo "Bot API kapalı (port ${PORT})"
fi

echo ""
echo "=== Önerilen GCP bölgesi ==="
echo "En düşük fapi.binance.com total süresine sahip bölgeyi seçin (asia-northeast1 / asia-southeast1)."
