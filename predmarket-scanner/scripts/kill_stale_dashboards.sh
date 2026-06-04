#!/usr/bin/env bash
# Eski / çoklu dashboard.py süreçlerini kapatır (binance_elite_pro dokunulmaz).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "Çalışan dashboard.py süreçleri:"
pgrep -fl "dashboard\.py" || true
echo ""
read -r -p "Hepsini sonlandır? [y/N] " ans
if [[ "${ans,,}" != "y" ]]; then
  echo "İptal."
  exit 0
fi
pkill -f "dashboard\.py" 2>/dev/null || true
sleep 1
if pgrep -f "dashboard\.py" >/dev/null 2>&1; then
  echo "Bazı süreçler hâlâ ayakta — elle: pgrep -fl dashboard.py"
else
  echo "✓ dashboard süreçleri kapandı."
fi
