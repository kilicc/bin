#!/usr/bin/env bash
# Tüm paper sepetleri — INSANE + katmanlı giriş (8000 + 8010-8050)
set -euo pipefail
cd "$(dirname "$0")"
PY="${PY:-./.venv/bin/python}"

export STACK_PROFILE=daily_2x_stack

# Ana :8000 — stack env ile
if ! lsof -ti:8000 >/dev/null 2>&1; then
  (
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
    mkdir -p data/scenario_pids
    nohup "$PY" dashboard.py >> data/dashboard_daily_2x.log 2>&1 &
    echo $! > data/scenario_pids/daily_2x_dash.pid
    sleep 2
    nohup "$PY" momentum_scanner.py >> data/daily_2x_scanner.log 2>&1 &
    echo $! > data/scenario_pids/daily_2x_scanner.pid
    echo "  Ana paper :8000 (katmanlı) başlatıldı"
  )
else
  echo "  :8000 dolu — ana atlandı"
fi

# Senaryo panelleri — her dashboard/scanner'a stack env enjekte et
SCEN_DIR="scenarios"
PID_DIR="data/scenario_pids"
mkdir -p "$PID_DIR"

export INSANE_24H=1
export STACK_PROFILE=daily_2x_stack
./run_paper_scenarios.sh

echo ""
echo "Paneller:"
echo "  8000 ana  |  8010 \$110  |  8020 \$220  |  8030 \$2200"
echo "  (8040/8050 için ayrıca ./run_paper_22k_insane_stack.sh)"
echo "Log: data/daily_2x_scanner.log, data/multi_paper_scanner.log"
