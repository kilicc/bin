#!/usr/bin/env bash
# Tüm modlar: arşiv + geçmiş sil + borsa kapat + 9005 restart (Evrim unified bootstrap)
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${PY:-./.venv/bin/python}"
REASON="${1:-evrim_unified_system_reset}"

echo "══════════════════════════════════════════════════════════"
echo " Evrim unified — tüm mod sıfırlama + restart"
echo "══════════════════════════════════════════════════════════"

"$PY" scripts/reset_all_modes_trades.py --reason "$REASON"

echo ""
echo "  🧬 Evrim unified bootstrap..."
PYTHONPATH=. "$PY" -c "
from elite_trader.evrim_unified_engine import bootstrap_unified_engine
print(bootstrap_unified_engine())
"

./run_binance_elite_8300_9005.sh
echo "══════════════════════════════════════════════════════════"
echo " Tamam. Panel: http://127.0.0.1:9005"
echo " Risk raporu: GET /api/evrim/unified/risk-report"
echo "══════════════════════════════════════════════════════════"
