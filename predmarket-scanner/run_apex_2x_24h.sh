#!/usr/bin/env bash
# APEX 2×24H — ana paper :8000 ($22k hedef → ~$44k / 24s, garanti değil)
set -euo pipefail
cd "$(dirname "$0")"
PY="${PY:-./.venv/bin/python}"

if [[ ! -x "$PY" ]]; then
  echo "venv yok: python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt"
  exit 1
fi

unset POLYMARKET_LIVE_TRADING POLYMARKET_LIVE_CONFIRM POLYMARKET_LIVE_ARMED

for pat in "momentum_scanner.py" "dashboard.py"; do
  pids=$(pgrep -f "$pat" 2>/dev/null || true)
  [[ -n "$pids" ]] && kill $pids 2>/dev/null || true
done
if lsof -ti:8000 >/dev/null 2>&1; then
  lsof -ti:8000 | xargs kill 2>/dev/null || true
  sleep 1
fi
rm -f data/polymarket_scanner_paper.lock 2>/dev/null || true

set -a
# shellcheck disable=SC1091
source .env 2>/dev/null || true
unset POLYMARKET_LIVE_TRADING POLYMARKET_LIVE_CONFIRM
# shellcheck disable=SC1091
source scenarios/insane_24h.env
# shellcheck disable=SC1091
source scenarios/apex_2x_24h.env
export INSANE_24H=1
export APEX_2X_24H=1
set +a

BAL="${STARTING_BALANCE:-22000}"
TARGET=$(echo "$BAL * ${APEX_TARGET_MULTIPLIER:-2}" | bc 2>/dev/null || echo "44000")

echo "══════════════════════════════════════════════════════════"
echo " APEX 2×24H  —  http://127.0.0.1:8000  (paper.db)"
echo "  Başlangıç: \$${BAL}  →  Hedef: ~\$${TARGET} (24s)"
echo "  Profil v${PROFILE_VERSION:-?}  |  max \$${MAX_POSITION_USD}/poz"
echo "  Katman: \${STACK_MAX_PER_MARKET}/market  |  Hibrit TP + öğrenme AÇIK"
echo "  Ctrl+C ile durdur"
echo "══════════════════════════════════════════════════════════"

"$PY" dashboard.py &
DPID=$!
trap 'kill $DPID 2>/dev/null || true' EXIT INT TERM
sleep 2
exec "$PY" momentum_scanner.py
