#!/usr/bin/env bash
# Taşınabilir Cursor projesi zip'i — kaynak + snapshot (venv hariç)
# Kullanım: ./scripts/export_portable_cursor_bundle.sh [SNAPSHOT_DIR]
set -euo pipefail
cd "$(dirname "$0")/.."
TS=$(date -u +%Y%m%dT%H%M%SZ)
STAGE="data/backups/_portable_stage_${TS}"
ZIP="data/backups/PORTABLE_CURSOR_BUNDLE_${TS}.zip"

SNAP="${1:-}"
if [[ -z "$SNAP" ]]; then
  SNAP=$(ls -td data/backups/PROJECT_FULL_SNAPSHOT_* 2>/dev/null | head -1)
fi
if [[ -z "$SNAP" || ! -d "$SNAP" ]]; then
  echo "Önce snapshot alın: ./scripts/backup_full_project_snapshot.sh"
  exit 1
fi

echo "══════════════════════════════════════════════════════════"
echo " Taşınabilir bundle → $ZIP"
echo " Snapshot: $SNAP"
echo "══════════════════════════════════════════════════════════"

rm -rf "$STAGE"
mkdir -p "$STAGE/predmarket-scanner"

rsync -a \
  --exclude '.venv' \
  --exclude '__pycache__' \
  --exclude '.git' \
  --exclude 'data/backups' \
  --exclude '*.pyc' \
  ./ "$STAGE/predmarket-scanner/"

# Snapshot overlay (güncel ayar + veri)
ROOT=$(pwd)
(cd "$STAGE/predmarket-scanner" && "$ROOT/scripts/restore_snapshot_overlay.sh" "$ROOT/$SNAP")

# Kılavuzlar kökte
for doc in KURULUM_YENI_CURSOR_PROJESI.md GERI_YUKLEME_PROJE.md SOHBET_REFERANS.md AYARLAR_TUM_PORTLAR.md; do
  [[ -f "$doc" ]] && cp -a "$doc" "$STAGE/predmarket-scanner/"
done

cat >"$STAGE/predmarket-scanner/OKU_BENI_ILK.txt" <<'EOF'
Predmarket Elite — taşınabilir paket

1. Bu klasörü Cursor'da Open Folder ile açın.
2. Terminal:
   python3 -m venv .venv
   ./.venv/bin/pip install -r requirements.txt
   ./run_elite_apex_2x_8200.sh --bg
3. Panel: http://127.0.0.1:8200/
4. Detay: KURULUM_YENI_CURSOR_PROJESI.md
EOF

(cd "$STAGE" && zip -rq "$ROOT/$ZIP" predmarket-scanner)
rm -rf "$STAGE"

echo ""
echo "  Hazır: $ZIP"
du -sh "$ZIP"
