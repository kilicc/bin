#!/usr/bin/env bash
# Evrim MTF backtest — 4–8 GB RAM tüketen arka plan süreçleri
set -euo pipefail
echo "evrim_mtf_backtest süreçleri:"
pgrep -fl "evrim_mtf_backtest" || echo "  (yok)"
pkill -f "evrim_mtf_backtest\.py" 2>/dev/null || true
sleep 1
if pgrep -f "evrim_mtf_backtest" >/dev/null 2>&1; then
  echo "⚠ Bazı süreçler hâlâ çalışıyor"
  pgrep -fl "evrim_mtf_backtest"
  exit 1
fi
echo "✓ evrim_mtf_backtest durduruldu"
