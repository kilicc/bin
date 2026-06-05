#!/usr/bin/env bash
# Demo paper panel + öğrenen tarayıcı (http://127.0.0.1:8000 değişmez)
set -euo pipefail
cd "$(dirname "$0")"
PY="${PY:-./.venv/bin/python}"

if [[ ! -x "$PY" ]]; then
  echo "venv yok: python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt"
  exit 1
fi

# Canlı bayrakları bu süreçte kapalı kalsın
unset POLYMARKET_LIVE_TRADING POLYMARKET_LIVE_CONFIRM POLYMARKET_LIVE_ARMED

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

echo "Dashboard: http://127.0.0.1:8000  (paper.db)  [APEX 2×24H v${PROFILE_VERSION:-1}]"
echo "Tarayıcı:  paper.db + self_improver"
echo "Ctrl+C ile durdur."

# Aynı DB'ye yazan eski paper tarayıcıları kapat (çift giriş önleme)
if command -v pkill >/dev/null 2>&1; then
  pkill -f "momentum_scanner.py" 2>/dev/null || true
  sleep 1
fi
rm -f data/polymarket_scanner_paper.lock 2>/dev/null || true

"$PY" dashboard.py &
DPID=$!
trap 'kill $DPID 2>/dev/null || true' EXIT INT TERM
sleep 2
"$PY" momentum_scanner.py
