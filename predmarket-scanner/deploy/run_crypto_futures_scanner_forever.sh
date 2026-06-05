#!/usr/bin/env bash
# Çökme sonrası yeniden başlatır. Log: data/crypto_futures_scanner.log
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PY="${ROOT}/.venv/bin/python"
LOG="${ROOT}/data/crypto_futures_scanner.log"
mkdir -p "${ROOT}/data"
echo "[$(date -Iseconds)] run_crypto_futures_scanner_forever başlıyor" >>"$LOG"
while true; do
  echo "[$(date -Iseconds)] crypto_futures_scanner.py başlatılıyor" >>"$LOG"
  if "$PY" "${ROOT}/crypto_futures_scanner.py" >>"$LOG" 2>&1; then
    echo "[$(date -Iseconds)] normal çıkış (kod 0)" >>"$LOG"
    exit 0
  fi
  echo "[$(date -Iseconds)] çöküş — 15s sonra yeniden" >>"$LOG"
  sleep 15
done
