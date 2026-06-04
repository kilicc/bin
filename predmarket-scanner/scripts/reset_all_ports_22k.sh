#!/usr/bin/env bash
# Tüm panel portları — trade DB + scan_stats sıfır, $22.000 başlangıç
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${PY:-./.venv/bin/python}"
TS=$(date -u +%Y%m%dT%H%M%SZ)
ARCHIVE="data/backups/reset_${TS}"
PORTS=(8150 8160 8170 8180 8190 8200 8000 8010 8020 8030 8040 8050)

echo "══════════════════════════════════════════════════════════"
echo " TÜM PORTLAR — sıfır DB, STARTING_BALANCE=22000"
echo "══════════════════════════════════════════════════════════"

# Süreçleri durdur
for port in "${PORTS[@]}"; do
  if lsof -ti :"${port}" >/dev/null 2>&1; then
    echo "  Port ${port} durduruluyor..."
    lsof -ti :"${port}" | xargs kill 2>/dev/null || true
  fi
done
for pat in "elite_trader.scanner" "dashboard.py" "momentum_scanner.py" "multi_paper_scanner.py"; do
  pids=$(pgrep -f "$pat" 2>/dev/null || true)
  [[ -n "$pids" ]] && kill $pids 2>/dev/null || true
done
sleep 2
rm -f .pids/*.pid data/scenario_pids/*.pid 2>/dev/null || true

mkdir -p "$ARCHIVE"
echo "  Arşiv: ${ARCHIVE}/"

# Trade DB'leri arşivle + sil
for db in data/*.db; do
  [[ -f "$db" ]] || continue
  base=$(basename "$db")
  case "$base" in
    live.db) echo "  atlandı (canlı): $base"; continue ;;
  esac
  mv "$db" "${ARCHIVE}/${base}"
  echo "  arşiv: $base"
done

# Scan stats, heartbeat, lock, attribution raporları
for f in data/scan_stats_*.json data/*.heartbeat.json data/*.lock data/polymarket_scanner*.lock; do
  [[ -e "$f" ]] || continue
  mv "$f" "${ARCHIVE}/" 2>/dev/null && echo "  arşiv: $(basename "$f")" || true
done
[[ -d data/reports ]] && mv data/reports "${ARCHIVE}/reports" && mkdir -p data/reports

# Boş DB'ler
"$PY" << 'PY'
from pathlib import Path
import momentum_scanner as ms
from elite_trader.db import init_db

root = Path("data")
root.mkdir(exist_ok=True)

elite_dbs = [
    "elite_formula.db",
    "elite_formula_cal.db",
    "elite_formula_velocity.db",
    "elite_global_2x.db",
    "elite_formula_8190_fresh.db",
    "elite_apex_2x_24h.db",
]
paper_dbs = [
    "paper.db",
    "paper_110.db",
    "paper_220.db",
    "paper_2200.db",
    "paper_22k.db",
    "paper_22k_insane.db",
]

for name in elite_dbs:
    init_db(root / name).close()
    print(f"  elite: {name}")

for name in paper_dbs:
    ms.init_db(root / name).close()
    print(f"  paper: {name}")

print("  Tamam — tüm trade DB boş.")
PY

# .env STARTING_BALANCE
if grep -q '^STARTING_BALANCE=' .env 2>/dev/null; then
  if [[ "$(uname)" == Darwin ]]; then
    sed -i '' 's/^STARTING_BALANCE=.*/STARTING_BALANCE=22000/' .env
  else
    sed -i 's/^STARTING_BALANCE=.*/STARTING_BALANCE=22000/' .env
  fi
else
  echo 'STARTING_BALANCE=22000' >> .env
fi

# Küçük sepet senaryoları da $22k (kullanıcı isteği)
for f in scenarios/paper_110.env scenarios/paper_220.env scenarios/paper_2200.env; do
  [[ -f "$f" ]] || continue
  if [[ "$(uname)" == Darwin ]]; then
    sed -i '' 's/^STARTING_BALANCE=.*/STARTING_BALANCE=22000/' "$f"
  else
    sed -i 's/^STARTING_BALANCE=.*/STARTING_BALANCE=22000/' "$f"
  fi
done

echo ""
echo "  STARTING_BALANCE=22000 (.env + paper_110/220/2200)"
echo "  Yeniden başlat:"
echo "    ./run_elite_cal_primary_stack.sh      # 8150"
echo "    ./run_elite_formula_restart_8160.sh   # 8160"
echo "    ./run_elite_velocity_stack.sh         # 8170"
echo "    ./run_elite_global_2x_stack.sh        # 8180"
echo "    ./run_elite_formula_fresh_8190.sh     # 8190"
echo "    ./run_elite_apex_2x_8200.sh --bg      # 8200"
echo "══════════════════════════════════════════════════════════"
