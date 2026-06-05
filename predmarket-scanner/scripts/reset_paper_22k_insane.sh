#!/usr/bin/env bash
# paper_22k_insane.db sıfırla — $22,000 başlangıç (port 8050)
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${PY:-./.venv/bin/python}"
TS=$(date -u +%Y%m%dT%H%M%SZ)
ARCHIVE="data1"
mkdir -p "$ARCHIVE"

if lsof -ti:8050 >/dev/null 2>&1; then
  echo "Port 8050 dolu — önce ./run_paper_22k_insane_stack.sh durdurun (Ctrl+C)"
  lsof -ti:8050 | xargs kill 2>/dev/null || true
  sleep 1
fi

if [[ -f data/paper_22k_insane.db ]]; then
  cp -a data/paper_22k_insane.db "${ARCHIVE}/paper_22k_insane_${TS}.db"
  rm -f data/paper_22k_insane.db
  echo "Arşiv: ${ARCHIVE}/paper_22k_insane_${TS}.db"
fi

"$PY" << 'PY'
from pathlib import Path
import momentum_scanner as ms
import backtest_trainer as bt

db = Path("data/paper_22k_insane.db")
conn = ms.init_db(db)
bt.init_shadow_db(conn)
conn.close()
print("Sıfır DB: data/paper_22k_insane.db  ($22,000)")
PY

echo "Başlat: ./run_paper_22k_insane_stack.sh"
