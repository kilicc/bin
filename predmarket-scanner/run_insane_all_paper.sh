#!/usr/bin/env bash
# Tüm paper varyasyonları — INSANE 24H profili (8000 + 8010-8040)
set -euo pipefail
cd "$(dirname "$0")"
PY="${PY:-./.venv/bin/python}"

echo "═══════════════════════════════════════════════════════════"
echo " INSANE 24H — tüm paper panelleri"
echo "  8000  ana paper.db (\$22k hedef 2×)"
echo "  8010  \$110  |  8020  \$220  |  8030  \$2200  (senkron)"
echo "  8040  \$22k alt (max \$220/poz)  |  8050  \$22k INSANE Full (yeni)"
echo "  Öğrenme: self_improver + backtest (paper DB)"
echo "═══════════════════════════════════════════════════════════"

# Ana paper (8000) — arka planda
if ! lsof -ti:8000 >/dev/null 2>&1; then
  (
    set -a
    # shellcheck disable=SC1091
    source .env 2>/dev/null || true
    # shellcheck disable=SC1091
    source scenarios/insane_24h.env
    set +a
    nohup "$PY" dashboard.py >> data/dashboard_main_insane.log 2>&1 &
    echo $! > data/scenario_pids/main_dash.pid
    sleep 2
    nohup "$PY" momentum_scanner.py >> data/main_paper_insane.log 2>&1 &
    echo $! > data/scenario_pids/main_scanner.pid
    echo "  Ana paper :8000 başlatıldı"
  )
else
  echo "  :8000 zaten dolu — ana paper atlandı"
fi

./run_paper_scenarios.sh
(
  set -a
  # shellcheck disable=SC1091
  source .env 2>/dev/null || true
  # shellcheck disable=SC1091
  source scenarios/insane_24h.env
  # shellcheck disable=SC1091
  source scenarios/paper_22k.env
  set +a
  if ! lsof -ti:8040 >/dev/null 2>&1; then
    nohup "$PY" dashboard.py >> data/dashboard_paper_22k.log 2>&1 &
    echo $! > data/scenario_pids/paper_22k_dash.pid
    sleep 2
    nohup "$PY" momentum_scanner.py >> data/paper_22k_insane.log 2>&1 &
    echo $! > data/scenario_pids/paper_22k_scanner.pid
    echo "  Paper 22k :8040 başlatıldı"
  else
    echo "  :8040 zaten dolu"
  fi
)

echo ""
echo "Durdurmak: ./scripts/stop_insane_all_paper.sh"
