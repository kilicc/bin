#!/usr/bin/env bash
# Sudo OLMADAN demo bot kurulumu (geçici — panel SSH tüneli ile)
set -euo pipefail

APP_ROOT="${APP_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
cd "${APP_ROOT}"

echo "=== Elite 9005 DEMO — kullanıcı kurulumu (sudo yok) ==="

if ! command -v python3.11 >/dev/null 2>&1 && ! command -v python3 >/dev/null 2>&1; then
  echo "HATA: python3 yok. GCP IAM → Compute OS Admin Login ile sudo bootstrap kullan." >&2
  exit 1
fi

PY=python3.11
command -v python3.11 >/dev/null 2>&1 || PY=python3

mkdir -p logs data .pids
chmod +x run_binance_elite_8300_9005.sh scripts/*.sh 2>/dev/null || true

if [[ ! -d .venv ]]; then
  "${PY}" -m venv .venv
fi
.venv/bin/pip install -U pip wheel -q
.venv/bin/pip install -r requirements.txt -q

# localhost only — dışarıya port açmaz
export ELITE_BIND_HOST=127.0.0.1
export NO_PROXY='*'

./scripts/elite_9005_process_ctl.sh stop 0 2>/dev/null || true
./run_binance_elite_8300_9005.sh

sleep 4
if curl -sf -m 5 http://127.0.0.1:9005/api/connection/live >/dev/null; then
  echo ""
  echo "OK — bot çalışıyor (127.0.0.1:9005)"
  echo ""
  echo "Mac'te panel için (yeni terminal):"
  echo "  ssh -i ~/.ssh/id_ed25519 -L 9005:127.0.0.1:9005 asilsoykan035@34.104.243.96"
  echo "  Tarayıcı: http://127.0.0.1:9005/"
else
  echo "Bot başlamadı — log: tail -f logs/binance_elite_8300_9005.log" >&2
  exit 1
fi
