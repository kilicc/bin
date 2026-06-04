#!/usr/bin/env bash
# 9005 korumalı veri + .env taşıma (cutover)
set -euo pipefail

REMOTE="${1:-}"
if [[ -z "${REMOTE}" ]]; then
  echo "Kullanım: $0 user@GCP_IP" >&2
  exit 1
fi

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "=== Cutover öncesi Mac bot durduruluyor ==="
if [[ -x scripts/elite_9005_process_ctl.sh ]]; then
  ./scripts/elite_9005_process_ctl.sh stop 0 || ./scripts/elite_9005_process_ctl.sh force-stop || true
fi

DB="data/binance_elite_8300_9005_state.db"
if [[ -f "${DB}" ]]; then
  cp "${DB}" "data/pre_gcp_cutover_$(date -u +%Y%m%dT%H%M%SZ).db"
  echo "DB snapshot alındı."
fi

echo "=== rsync data/ (korumalı dosyalar) ==="
rsync -avz --progress \
  data/binance_elite_8300_9005_state.db \
  data/elite_9005_trade_lessons.json \
  data/elite_9005_learning_registry.json \
  data/elite_9005_proposals.json \
  data/elite_sl_emergency_registry.json \
  data/elite_9005_loss_postmortem.json \
  data/elite_9005_loss_postmortem.md \
  data/parallel_universes.json \
  data/deleted_archives/ \
  "${REMOTE}:/opt/binancex/predmarket-scanner/data/" 2>/dev/null || \
rsync -avz --progress data/ "${REMOTE}:/opt/binancex/predmarket-scanner/data/"

echo "=== .env (mainnet anahtarları) ==="
if [[ ! -f .env ]]; then
  echo "UYARI: .env yok — sunucuda manuel oluşturun" >&2
else
  rsync -avz .env "${REMOTE}:/opt/binancex/predmarket-scanner/.env"
  ssh "${REMOTE}" "chmod 600 /opt/binancex/predmarket-scanner/.env"
fi

echo ""
echo "Cutover tamam. Sunucuda:"
echo "  sudo systemctl restart binance-elite-9005-mainnet elite-9005-supervisor"
echo "  ./scripts/gcp_go_live_check.sh https://panel.example.com"
