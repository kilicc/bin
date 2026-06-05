#!/usr/bin/env bash
# MEGA mainnet — port 9086 (İlk Cloud Import Konfigürasyonu)
set -euo pipefail
cd "$(dirname "$0")"
exec ./.venv/bin/python binance_elite_pro_9086_mainnet.py
