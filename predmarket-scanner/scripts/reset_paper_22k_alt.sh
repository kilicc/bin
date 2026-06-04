#!/usr/bin/env bash
# paper_22k.db sıfırla — $22,000 başlangıç (port 8040 stack)
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${PY:-./.venv/bin/python}"
TS=$(date -u +%Y%m%dT%H%M%SZ)
ARCHIVE="data1"

for pat in "dashboard.py" "momentum_scanner.py"; do
  pids=$(pgrep -f "$pat" 2>/dev/null || true)
  if [[ -n "$pids" ]]; then
    echo "Uyarı: $pat çalışıyor — önce ./run_paper_22k_stack.sh durdurun veya port 8040"
  fi
done

mkdir -p "$ARCHIVE"
if [[ -f data/paper_22k.db ]]; then
  cp -a data/paper_22k.db "${ARCHIVE}/paper_22k_${TS}.db"
  rm -f data/paper_22k.db
  echo "Arşiv: ${ARCHIVE}/paper_22k_${TS}.db"
fi

"$PY" << 'PY'
from pathlib import Path
import momentum_scanner as ms
import backtest_trainer as bt

db = Path("data/paper_22k.db")
conn = ms.init_db(db)
bt.init_shadow_db(conn)
conn.close()
print(f"Sıfır DB: {db}  STARTING_BALANCE=22000")
PY

echo "Başlat: ./run_paper_22k_stack.sh"
