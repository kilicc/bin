#!/usr/bin/env bash
# Çökme sonrası yeniden başlatır. Log: data/crypto_engine.log
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PY="${ROOT}/.venv/bin/python"
LOG="${ROOT}/data/crypto_engine.log"
mkdir -p "${ROOT}/data"
echo "[$(date -Iseconds)] run_crypto_engine_forever başlıyor" >>"$LOG"
while true; do
  echo "[$(date -Iseconds)] crypto_engine.py başlatılıyor" >>"$LOG"
  if "$PY" "${ROOT}/crypto_engine.py" >>"$LOG" 2>&1; then
    echo "[$(date -Iseconds)] normal çıkış (kod 0)" >>"$LOG"
    exit 0
  fi
  echo "[$(date -Iseconds)] çöküş — 15s sonra yeniden" >>"$LOG"
  sleep 15
done
