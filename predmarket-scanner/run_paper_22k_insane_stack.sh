#!/usr/bin/env bash
# Paper $22k tam INSANE — sıfırdan, port 8050 (8040 paper_22k: max $220/poz ayrı kalır)
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
unset POLYMARKET_LIVE_TRADING POLYMARKET_LIVE_CONFIRM
# shellcheck disable=SC1091
source scenarios/insane_24h.env
# shellcheck disable=SC1091
source scenarios/paper_22k_insane.env
set +a

echo "=== Paper 22k INSANE Full (yeni) ==="
echo "  Panel:     http://127.0.0.1:${DASHBOARD_PORT}"
echo "  DB:        ${PAPER_DB_PATH}"
echo "  Başlangıç: \$${STARTING_BALANCE}"
echo "  Max/poz:   \$${MAX_POSITION_USD}  |  Hedef ~\$${PAPER_TARGET_STAKE_USD}"
echo "  Açık cap:  ${PAPER_MAX_OPEN_STAKE_PCT} bakiye (≈\$18000)"
echo "  SL/TP:     -${STOP_LOSS_STAKE_PCT} / +${TAKE_PROFIT_STAKE_PCT} stake (INSANE katmanlı)"
echo "  Sıfırla:   ./scripts/reset_paper_22k_insane.sh"
echo "  Ctrl+C ile durdur."
echo ""

"$PY" << 'PY'
from pathlib import Path
import momentum_scanner as ms
import backtest_trainer as bt

db = Path("data/paper_22k_insane.db")
if not db.exists():
    conn = ms.init_db(db)
    bt.init_shadow_db(conn)
    conn.close()
    print(f"  Yeni DB: {db}")
else:
    print(f"  DB mevcut: {db}")
PY

"$PY" dashboard.py &
DPID=$!
trap 'kill $DPID 2>/dev/null || true' EXIT INT TERM
sleep 2
exec "$PY" momentum_scanner.py
