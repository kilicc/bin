#!/usr/bin/env bash
# live.db geçmişini arşivle, boş DB ile WR/PnL sıfırdan başla (paper.db dokunulmaz).
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${PY:-./.venv/bin/python}"
DB="${LIVE_DB_PATH:-data/live.db}"
ARCHIVE_DIR="data1"

mkdir -p "$ARCHIVE_DIR"

# Yalnızca canlı tarayıcıyı durdur (paper stack kalır)
if [[ -f data/polymarket_scanner.lock ]]; then
  lock_pid=$(cat data/polymarket_scanner.lock 2>/dev/null || true)
  if [[ -n "$lock_pid" ]] && kill -0 "$lock_pid" 2>/dev/null; then
    echo "Canlı tarayıcı durduruluyor (PID $lock_pid)…"
    kill "$lock_pid" 2>/dev/null || true
    sleep 2
  fi
fi

TS=$(date -u +%Y%m%dT%H%M%SZ)
if [[ -f "$DB" ]]; then
  bak="${ARCHIVE_DIR}/live_${TS}.db"
  cp -a "$DB" "$bak"
  echo "Arşiv: $DB → $bak"
  rm -f "$DB"
fi

"$PY" << 'PY'
from pathlib import Path
import momentum_scanner as ms
import backtest_trainer as bt

db = Path("data/live.db")
conn = ms.init_db(db)
bt.init_shadow_db(conn)
conn.execute("DELETE FROM shadow_observations")
conn.commit()
conn.close()
print(f"Yeni boş DB: {db}")
PY

echo ""
echo "Tamam — live WR/PnL sıfır. Canlı tarayıcıyı yeniden başlatın:"
echo "  ./run_live_scanner.sh"
