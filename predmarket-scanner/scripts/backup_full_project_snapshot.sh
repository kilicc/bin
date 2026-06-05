#!/usr/bin/env bash
# Tam proje anlık görüntüsü — ayarlar, DB, modeller, elite kodu, loglar
# Kullanım: ./scripts/backup_full_project_snapshot.sh
set -euo pipefail
cd "$(dirname "$0")/.."
TS=$(date -u +%Y%m%dT%H%M%SZ)
DEST="data/backups/PROJECT_FULL_SNAPSHOT_${TS}"
mkdir -p "$DEST"/{config/scenarios,config/run_scripts,data/dbs,data/pkl,data/scan_stats,code/elite_trader,logs,reports}

echo "══════════════════════════════════════════════════════════"
echo " TAM PROJE YEDEĞİ → ${DEST}"
echo "══════════════════════════════════════════════════════════"

# Senaryo + kök env + run scriptler
cp -a scenarios/*.env "$DEST/config/scenarios/" 2>/dev/null || true
[[ -f .env ]] && cp -a .env "$DEST/config/dotenv_root.env"
cp -a run_elite*.sh "$DEST/config/run_scripts/"
cp -a run_binance*.sh "$DEST/config/run_scripts/" 2>/dev/null || true
mkdir -p "$DEST/code/binance_futures_trader"
cp -a binance_elite_pro*.py "$DEST/code/" 2>/dev/null || true
cp -a binance_futures_trader/*.py "$DEST/code/binance_futures_trader/" 2>/dev/null || true
cp -a scripts/reset_all_ports_22k.sh scripts/backup_full_project_snapshot.sh "$DEST/config/run_scripts/" 2>/dev/null || true

# Veritabanları
for db in data/*.db; do
  [[ -f "$db" ]] || continue
  cp -a "$db" "$DEST/data/dbs/"
  echo "  db: $(basename "$db")"
done

# Modeller / öğrenme
for pkl in data/*.pkl; do
  [[ -f "$pkl" ]] || continue
  cp -a "$pkl" "$DEST/data/pkl/"
  echo "  pkl: $(basename "$pkl")"
done

# Scan stats
cp -a data/scan_stats_*.json "$DEST/data/scan_stats/" 2>/dev/null || true

# Raporlar
cp -a data/reports/* "$DEST/reports/" 2>/dev/null || true

# Elite kod (bu sohbette değişen modüller)
cp -a elite_trader/*.py "$DEST/code/elite_trader/"
cp -a dashboard.py momentum_scanner.py "$DEST/code/" 2>/dev/null || true

# Son loglar (8200 + diğer elite)
for f in logs/elite_apex_2x_8200.*.log logs/elite_formula*.log logs/elite_global*.log; do
  [[ -f "$f" ]] && cp -a "$f" "$DEST/logs/" 2>/dev/null || true
done

# DB özetleri
{
  echo "Snapshot: ${TS} UTC"
  echo ""
  for db in "$DEST"/data/dbs/*.db; do
    [[ -f "$db" ]] || continue
    b=$(basename "$db")
    echo "=== $b ==="
    sqlite3 "$db" "
      SELECT 'open', COUNT(*) FROM positions WHERE closed_at IS NULL;
      SELECT 'closed', COUNT(*) FROM positions WHERE closed_at IS NOT NULL;
      SELECT 'pnl', ROUND(COALESCE(SUM(pnl_usd),0),2) FROM positions WHERE closed_at IS NOT NULL;
    " 2>/dev/null || echo "(sqlite okunamadı)"
    echo ""
  done
} >"$DEST/db_summaries.txt"

# Manifest
(
  cd "$DEST"
  find . -type f ! -name 'MANIFEST.sha256' | sort | while read -r f; do
    shasum -a 256 "$f"
  done
) >"$DEST/MANIFEST.sha256"

# Kılavuzları kopyala (repo kökündeki güncel sürüm)
for doc in GERI_YUKLEME_PROJE.md KURULUM_YENI_CURSOR_PROJESI.md SOHBET_REFERANS.md AYARLAR_TUM_PORTLAR.md BINANCE_DEMO_KURULUM_KAYIT.md; do
  [[ -f "$doc" ]] && cp -a "$doc" "$DEST/"
done
cp -a scripts/restore_snapshot_overlay.sh scripts/export_portable_cursor_bundle.sh "$DEST/config/run_scripts/" 2>/dev/null || true

echo ""
echo "  Tamamlandı: ${DEST}"
echo "  Geri yükleme: ${DEST}/GERI_YUKLEME_PROJE.md"
du -sh "$DEST" 2>/dev/null || true
