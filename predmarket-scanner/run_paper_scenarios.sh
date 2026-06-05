#!/usr/bin/env bash
# 3 senkron paper senaryosu: $110 / $220 / $2200 — TP 1% / SL 5% stake
set -euo pipefail
cd "$(dirname "$0")"
PY="${PY:-./.venv/bin/python}"
SCEN_DIR="scenarios"
PID_DIR="data/scenario_pids"
mkdir -p "$PID_DIR"

if [[ ! -x "$PY" ]]; then
  echo "venv yok: python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt"
  exit 1
fi

unset POLYMARKET_LIVE_TRADING POLYMARKET_LIVE_CONFIRM
export INSANE_24H=1
if [[ "${STACK_PROFILE:-}" == "daily_2x_stack" && -f scenarios/daily_2x_stack.env ]]; then
  # shellcheck disable=SC1091
  source scenarios/daily_2x_stack.env
fi

stop_one() {
  local f="$1"
  if [[ -f "$f" ]]; then
    local pid
    pid=$(cat "$f" 2>/dev/null || true)
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
    fi
    rm -f "$f"
  fi
}

echo "=== Paper senaryoları (senkron) ==="
echo '  $110   → http://127.0.0.1:8010'
echo '  $220   → http://127.0.0.1:8020'
echo '  $2200  → http://127.0.0.1:8030'
echo "  Profil: INSANE 24H (hızlı TP, %50 Kelly, senkron işlem)"
echo ""

# Eski senaryo süreçleri
shopt -s nullglob
for f in "$PID_DIR"/*.pid; do
  stop_one "$f"
done
shopt -u nullglob
if pgrep -f "multi_paper_scanner.py" >/dev/null 2>&1; then
  pkill -f "multi_paper_scanner.py" 2>/dev/null || true
  sleep 1
fi

# Boş DB'ler
"$PY" << 'PY'
from paper_scenarios import DEFAULT_SCENARIOS, init_scenario_db
for s in DEFAULT_SCENARIOS:
    init_scenario_db(s)
    print(f"  DB hazır: {s.db_path.name} (${s.starting_balance:,.0f})")
PY

start_dashboard() {
  local envfile="$1"
  local name
  name=$(basename "$envfile" .env)
  (
    set -a
    # shellcheck disable=SC1091
    source .env 2>/dev/null || true
    # shellcheck disable=SC1091
    source "$SCEN_DIR/insane_24h.env" 2>/dev/null || true
    if [[ "${STACK_PROFILE:-}" == "daily_2x_stack" && -f scenarios/daily_2x_stack.env ]]; then
      # shellcheck disable=SC1091
      source scenarios/daily_2x_stack.env
    fi
    # shellcheck disable=SC1090
    source "$SCEN_DIR/$envfile"
    set +a
    exec "$PY" dashboard.py
  ) >> "data/dashboard_${name}.log" 2>&1 &
  echo $! > "$PID_DIR/${name}_dash.pid"
  echo "  Panel $name → port $(grep '^DASHBOARD_PORT=' "$SCEN_DIR/$envfile" | cut -d= -f2) (PID $(cat "$PID_DIR/${name}_dash.pid"))"
}

for ef in paper_110.env paper_220.env paper_2200.env; do
  start_dashboard "$ef"
done

sleep 2

echo ""
echo "  Tarayıcı (tek süreç, 3 DB senkron)…"
(
  set -a
  # shellcheck disable=SC1091
  source .env 2>/dev/null || true
  # shellcheck disable=SC1091
  source "$SCEN_DIR/insane_24h.env"
  if [[ "${STACK_PROFILE:-}" == "daily_2x_stack" && -f scenarios/daily_2x_stack.env ]]; then
    # shellcheck disable=SC1091
    source scenarios/daily_2x_stack.env
  fi
  set +a
  exec "$PY" multi_paper_scanner.py
) >> data/multi_paper_scanner.log 2>&1 &
echo $! > "$PID_DIR/multi_scanner.pid"
echo "  Scanner PID $(cat "$PID_DIR/multi_scanner.pid")"
echo ""
echo "Durdurmak: ./scripts/stop_paper_scenarios.sh"
echo "Log: data/multi_paper_scanner.log"
