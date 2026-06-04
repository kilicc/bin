#!/usr/bin/env bash
# Paper $22k — sıfırdan, port 8040, max $220/pozisyon, açık stake ≤ %35 bakiye
set -euo pipefail
cd "$(dirname "$0")"
PY="${PY:-./.venv/bin/python}"

if [[ ! -x "$PY" ]]; then
  echo "venv yok: python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt"
  exit 1
fi

unset POLYMARKET_LIVE_TRADING POLYMARKET_LIVE_CONFIRM
export INSANE_24H=1

set -a
# shellcheck disable=SC1091
source .env 2>/dev/null || true
# shellcheck disable=SC1091
source scenarios/insane_24h.env
# shellcheck disable=SC1091
source scenarios/paper_22k.env
set +a

echo "=== Paper 22k INSANE 24H ==="
echo "  Panel:    http://127.0.0.1:${DASHBOARD_PORT}"
echo "  DB:       ${PAPER_DB_PATH}"
echo "  Başlangıç: \$${STARTING_BALANCE}"
echo "  Max/poz:  \$${MAX_POSITION_USD}  |  Açık stake cap: ${PAPER_MAX_OPEN_STAKE_PCT} × bakiye (≈\$7700)"
echo "  Min stake: Kelly (sistem)"
echo "  Ctrl+C ile durdur."
echo ""

"$PY" << 'PY'
from pathlib import Path
import momentum_scanner as ms
import backtest_trainer as bt

db = Path("data/paper_22k.db")
if db.exists():
    print(f"  Mevcut DB: {db} (sıfırdan için: ./scripts/reset_paper_22k_alt.sh)")
else:
    conn = ms.init_db(db)
    bt.init_shadow_db(conn)
    conn.close()
    print(f"  Yeni DB: {db}")
PY

"$PY" dashboard.py &
DPID=$!
trap 'kill $DPID 2>/dev/null || true' EXIT INT TERM
sleep 2
exec "$PY" momentum_scanner.py
