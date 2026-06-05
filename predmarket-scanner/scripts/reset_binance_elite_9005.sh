#!/usr/bin/env bash
# Binance Elite 9005 — yeniden başlat
# Varsayılan: geçmiş veri KORUNUR (state DB, lessons, learner, log arşivi yok).
# Veri silmek için: ./scripts/reset_binance_elite_9005.sh --wipe-data --reason "neden"
set -euo pipefail
cd "$(dirname "$0")/.."

PORT=9005
STAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR="data/backups/reset_9005_${STAMP}"
STATE_DB="data/binance_elite_8300_9005_state.db"
LESSONS="data/elite_9005_trade_lessons.json"
APEX="data/apex_master/learned_formula.json"
LOG="logs/binance_elite_8300_9005.log"
PY="${PY:-./.venv/bin/python}"

WIPE_DATA=0
WIPE_REASON=""
CLOSE_EXCHANGE=1

while [[ $# -gt 0 ]]; do
  case "$1" in
    --wipe-data) WIPE_DATA=1; shift ;;
    --reason) WIPE_REASON="${2:-}"; shift 2 ;;
    --no-exchange-close) CLOSE_EXCHANGE=0; shift ;;
    --help|-h)
      echo "Kullanım: $0 [--wipe-data --reason \"neden\"] [--no-exchange-close]"
      echo "  Varsayılan: sadece bot yeniden başlar, DB/öğrenme verisi kalır."
      echo "  --wipe-data: scripts/delete_9005_history.py ile aynı arşiv+sil akışı."
      exit 0
      ;;
    *) echo "Bilinmeyen argüman: $1"; exit 1 ;;
  esac
done

mkdir -p "$BACKUP_DIR" logs .pids

echo "══════════════════════════════════════════════════════════"
echo " Elite 9005 — yeniden başlat"
if [[ "$WIPE_DATA" -eq 1 ]]; then
  echo "  ⚠ --wipe-data: geçmiş veri arşivlenip silinecek"
else
  echo "  ✓ Geçmiş veri korunuyor (DB, lessons, learner)"
fi
echo "══════════════════════════════════════════════════════════"

# 1) Süreci durdur (tek örnek + port LISTEN)
# shellcheck disable=SC1091
source scripts/elite_9005_process_ctl.sh
elite_9005_stop 0 || elite_9005_stop 1
echo "  ✓ Port ${PORT} durduruldu"

# 2) Demo borsada kalan pozisyonları kapat (isteğe bağlı)
if [[ "$CLOSE_EXCHANGE" -eq 1 ]] && [[ -x "$PY" ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env 2>/dev/null || true
  # shellcheck disable=SC1091
  source scenarios/binance_elite_8300_9005.env 2>/dev/null || true
  export BN_FUT_MODE=testnet BINANCE_FUTURES_TESTNET=1 BINANCE_FUTURES_DEMO=1
  set +a
  "$PY" <<'PY' || true
import os, time
os.environ.setdefault("BN_FUT_MODE", "testnet")
from binance_futures_trader import config as cfg
import importlib
importlib.reload(cfg)
from binance_futures_trader.client import BinanceFuturesClient
c = BinanceFuturesClient()
if c.paper:
    print("  ⚠ API paper — borsa kapanışı atlandı")
else:
    n = 0
    for ep in c.exchange_positions():
        coin = ep["coin"]
        side = "SHORT" if ep["side"] == "LONG" else "LONG"
        qty = c.round_qty(coin, float(ep["contracts"]))
        if qty > 0:
            c.market_order(coin, side, qty, reduce_only=True)
            print(f"  ✓ Borsa kapatıldı {ep['symbol']} {ep['side']} qty={qty}")
            n += 1
            time.sleep(0.2)
    print(f"  ✓ Demo borsa: {n} pozisyon kapatıldı" if n else "  ✓ Demo borsa: açık pozisyon yok")
    w = c.exchange_wallet()
    if w:
        bal = float(
            w.get("total_margin_balance")
            or w.get("total_wallet_balance")
            or 0
        )
        avail = float(w.get("available_balance") or bal)
        print(f"  ✓ Binance Futures bakiye: ${bal:,.2f} USDT (kullanılabilir ${avail:,.2f})")
PY
fi

# 3) Veri silme — YALNIZCA --wipe-data
if [[ "$WIPE_DATA" -eq 1 ]]; then
  if [[ -z "$WIPE_REASON" ]]; then
    echo "  ✗ --wipe-data için --reason \"...\" zorunlu"
    exit 1
  fi
  if [[ -x "$PY" ]]; then
    "$PY" scripts/delete_9005_history.py --reason "$WIPE_REASON" --yes
  else
    echo "  ✗ Python yok — wipe atlandı"
    exit 1
  fi
  # Log arşivi (veri silme isteğinde)
  if [[ -f "$LOG" ]]; then
    cp -a "$LOG" "${LOG}.${STAMP}.bak"
    : >"$LOG"
    echo "  ✓ Log arşivlendi → ${LOG}.${STAMP}.bak"
  fi
  # APEX sıfır (opsiyonel formül)
  if [[ -f "$APEX" ]]; then
    cp -a "$APEX" "$BACKUP_DIR/" 2>/dev/null || true
    cat >"$APEX" <<'JSON'
{
  "version": 1,
  "updated_at": "",
  "target_equity_mult": 2.0,
  "target_hours": 24.0,
  "active_capital_pct": 0.5,
  "min_edge": 0.045,
  "min_formula_score": 0.52,
  "avg_trader_wr": 0.58,
  "symbol_bias": {},
  "side_weights": {},
  "trades_analyzed": 0
}
JSON
    echo "  ✓ $APEX sıfırlandı"
  fi
else
  echo "  · State DB / lessons / learner korundu"
  [[ -f "$STATE_DB" ]] && echo "    → $STATE_DB ($(sqlite3 "$STATE_DB" 'SELECT COUNT(*) FROM closed_trades;' 2>/dev/null || echo '?') kapanış)"
fi

# 4) STARTING_BALANCE → Binance Futures cüzdan ile eşitle (ayar dosyası — isteğe bağlı senkron)
ENV_FILE="scenarios/binance_elite_8300_9005.env"
if [[ -x "$PY" ]]; then
  sync_line=$("$PY" <<'PY' 2>/dev/null || true
import os
os.environ.setdefault("BN_FUT_MODE", "testnet")
from binance_futures_trader import config as cfg
import importlib
importlib.reload(cfg)
from binance_futures_trader.client import BinanceFuturesClient
c = BinanceFuturesClient()
if c.paper:
    raise SystemExit(1)
w = c.exchange_wallet()
if not w:
    raise SystemExit(1)
bal = float(w.get("total_margin_balance") or w.get("total_wallet_balance") or 0)
print(f"{bal:.2f}")
PY
)
  if [[ -n "${sync_line:-}" ]] && [[ -f "$ENV_FILE" ]]; then
    if grep -q '^STARTING_BALANCE=' "$ENV_FILE"; then
      sed -i '' "s/^STARTING_BALANCE=.*/STARTING_BALANCE=${sync_line}/" "$ENV_FILE" 2>/dev/null \
        || sed -i "s/^STARTING_BALANCE=.*/STARTING_BALANCE=${sync_line}/" "$ENV_FILE"
    else
      echo "STARTING_BALANCE=${sync_line}" >>"$ENV_FILE"
    fi
    echo "  ✓ $ENV_FILE STARTING_BALANCE=${sync_line} (Binance Futures)"
  fi
  if [[ "$WIPE_DATA" -eq 1 ]] && [[ -n "${sync_line:-}" ]]; then
    "$PY" <<PY || true
from elite_trader.parallel_universe_engine import wipe_all_universes_fresh
out = wipe_all_universes_fresh(float("${sync_line}"))
print(
    f"  ✓ parallel_universes session_start=\${out.get('starting_capital', 0):,.2f} "
    f"({out.get('modes_reset', 0)} mod, borsa sonrası)"
)
PY
  fi
fi

echo ""
echo "  Silinen arşiv listesi: python3 scripts/list_9005_deleted_archives.py"
echo "  Başlat: ./run_binance_elite_8300_9005.sh"
echo "══════════════════════════════════════════════════════════"
