#!/usr/bin/env bash
# Küçük katmanlı paper — ana panel :8000, INSANE + daily_2x_stack profili
set -euo pipefail
cd "$(dirname "$0")"
PY="${PY:-./.venv/bin/python}"

if [[ ! -x "$PY" ]]; then
  echo "venv yok: python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt"
  exit 1
fi

unset POLYMARKET_LIVE_TRADING POLYMARKET_LIVE_CONFIRM POLYMARKET_LIVE_ARMED

set -a
# shellcheck disable=SC1091
source .env 2>/dev/null || true
unset POLYMARKET_LIVE_TRADING POLYMARKET_LIVE_CONFIRM
# shellcheck disable=SC1091
source scenarios/insane_24h.env
# shellcheck disable=SC1091
source scenarios/daily_2x_stack.env
export INSANE_24H=1
set +a

echo "══════════════════════════════════════════════════════════"
echo " Daily 2× stack — http://127.0.0.1:8000  (paper.db)"
echo "  Katman: max ${STACK_MAX_PER_MARKET}/market, ${STACK_MAX_SAME_SIDE}/taraf"
echo "  Stake:  ~\$${PAPER_MIN_POSITION_USD}-\$${MAX_POSITION_USD} (2.+ katman ×${STACK_STAKE_FRAC})"
echo "  Tüm sepetler: ./run_daily_2x_all_baskets.sh"
echo "══════════════════════════════════════════════════════════"

"$PY" dashboard.py &
DPID=$!
trap 'kill $DPID 2>/dev/null || true' EXIT INT TERM
sleep 2
exec "$PY" momentum_scanner.py
