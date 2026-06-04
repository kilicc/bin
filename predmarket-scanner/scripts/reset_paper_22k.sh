#!/usr/bin/env bash
# Eski data/ -> data1/ arsivi, 22000 USDC paper sifirdan, dashboard :8000
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${PY:-./.venv/bin/python}"
ROOT="$(pwd)"

echo "=== Paper 22000 USDC sifirlama ==="

# Çalışan süreçleri durdur
for pat in "dashboard.py" "momentum_scanner.py"; do
  pids=$(pgrep -f "$pat" 2>/dev/null || true)
  if [[ -n "$pids" ]]; then
    echo "Durduruluyor: $pat ($pids)"
    kill $pids 2>/dev/null || true
    sleep 1
  fi
done
if lsof -ti:8000 >/dev/null 2>&1; then
  echo "Port 8000 serbest bırakılıyor..."
  lsof -ti:8000 | xargs kill 2>/dev/null || true
  sleep 1
fi

TS=$(date -u +%Y%m%dT%H%M%SZ)
ARCHIVE="data1"
if [[ -d data ]] && [[ ! -d "$ARCHIVE" ]]; then
  echo "Arşiv: data/ → $ARCHIVE/"
  mv data "$ARCHIVE"
elif [[ -d data ]]; then
  echo "Arşiv: data/ → ${ARCHIVE}/snapshot_${TS}/"
  mkdir -p "$ARCHIVE"
  mv data "${ARCHIVE}/snapshot_${TS}"
else
  mkdir -p "$ARCHIVE"
fi

mkdir -p data

# Kalibrasyon pkl (tarihsel prior — trade geçmişi değil) arşivden kopyala
for f in calibration_data.pkl calibration_progress.pkl recent_trades.pkl history_trades.pkl whale_watchlist.pkl whale_watchlist_curated.pkl; do
  if [[ -f "$ARCHIVE/$f" ]]; then
    cp -a "$ARCHIVE/$f" "data/$f"
    echo "  kopyalandı: $f"
  elif [[ -d "$ARCHIVE" ]]; then
    src=$(find "$ARCHIVE" -maxdepth 2 -name "$f" -type f 2>/dev/null | head -1)
    if [[ -n "$src" ]]; then
      cp -a "$src" "data/$f"
      echo "  kopyalandı: $f (from $src)"
    fi
  fi
done

"$PY" << 'PY'
from pathlib import Path
import momentum_scanner as ms
import self_improver as si

root = Path(".")
ms.init_db(root / "data" / "paper.db").close()
ms.init_db(root / "data" / "live.db").close()
st = si.LearningState()
st.save()
print("  paper.db + live.db (boş) + learning_state.pkl (sıfır)")
PY

cat > data/README.md << EOF
# Paper strateji — \$22.000 (sıfır başlangıç)

- **Arşiv:** \`../data1/\` (önceki tüm veriler)
- **Başlangıç equity:** \$22,000 (STARTING_BALANCE in .env)
- **Panel:** http://127.0.0.1:8000 → \`paper.db\`
- **Canlı:** ayrı; \`./run_live_scanner.sh\` → \`live.db\`

Oluşturulma: ${TS} UTC
EOF

# .env STARTING_BALANCE güncelle
if grep -q '^STARTING_BALANCE=' .env 2>/dev/null; then
  if [[ "$(uname)" == Darwin ]]; then
    sed -i '' 's/^STARTING_BALANCE=.*/STARTING_BALANCE=22000/' .env
  else
    sed -i 's/^STARTING_BALANCE=.*/STARTING_BALANCE=22000/' .env
  fi
else
  echo 'STARTING_BALANCE=22000' >> .env
fi

echo ""
echo "Tamam. Başlatmak için:"
echo "  ./run_paper_stack.sh"
echo "  veya: ./.venv/bin/python dashboard.py"
