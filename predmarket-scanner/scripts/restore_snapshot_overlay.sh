#!/usr/bin/env bash
# Snapshot verisini mevcut (tam) proje köküne uygular — yeni Cursor klasöründe kullanın.
# Kullanım: ./scripts/restore_snapshot_overlay.sh data/backups/PROJECT_FULL_SNAPSHOT_XXXXX
set -euo pipefail
cd "$(dirname "$0")/.."

SNAP="${1:-}"
if [[ -z "$SNAP" || ! -d "$SNAP" ]]; then
  echo "Kullanım: $0 <PROJECT_FULL_SNAPSHOT klasörü>"
  exit 1
fi
SNAP=$(cd "$SNAP" && pwd)

echo "══════════════════════════════════════════════════════════"
echo " Snapshot overlay → $(pwd)"
echo " Kaynak: $SNAP"
echo "══════════════════════════════════════════════════════════"

mkdir -p scenarios data data/reports logs .pids

cp -a "$SNAP/config/scenarios/"* scenarios/ 2>/dev/null || true
[[ -f "$SNAP/config/dotenv_root.env" ]] && cp -a "$SNAP/config/dotenv_root.env" .env

for f in "$SNAP/config/run_scripts/"run_elite*.sh "$SNAP/config/run_scripts/"run_binance*.sh; do
  [[ -f "$f" ]] && cp -a "$f" ./
done
chmod +x run_elite*.sh run_binance*.sh 2>/dev/null || true

for f in binance_elite_pro.py binance_elite_pro_9005.py binance_elite_pro_9004.py; do
  [[ -f "$SNAP/code/$f" ]] && cp -a "$SNAP/code/$f" ./
done

cp -a "$SNAP/data/dbs/"* data/ 2>/dev/null || true
cp -a "$SNAP/data/pkl/"* data/ 2>/dev/null || true
mkdir -p data/reports
cp -a "$SNAP/data/scan_stats/"* data/ 2>/dev/null || true
cp -a "$SNAP/reports/"* data/reports/ 2>/dev/null || true

if [[ -d "$SNAP/code/elite_trader" ]]; then
  mkdir -p elite_trader
  cp -a "$SNAP/code/elite_trader/"* elite_trader/
fi
[[ -f "$SNAP/code/dashboard.py" ]] && cp -a "$SNAP/code/dashboard.py" dashboard.py
[[ -f "$SNAP/code/momentum_scanner.py" ]] && cp -a "$SNAP/code/momentum_scanner.py" momentum_scanner.py

cp -a "$SNAP/logs/"* logs/ 2>/dev/null || true

for doc in GERI_YUKLEME_PROJE.md SOHBET_REFERANS.md AYARLAR_TUM_PORTLAR.md KURULUM_YENI_CURSOR_PROJESI.md; do
  [[ -f "$SNAP/$doc" ]] && cp -a "$SNAP/$doc" ./
done

echo "  Tamam. Kontrol:"
echo "    ls scenarios/elite_apex_2x_24h.env"
echo "    ls data/elite_apex_2x_24h.db"
echo "    ./run_elite_apex_2x_8200.sh --bg"
