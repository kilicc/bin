#!/usr/bin/env bash
# MEGA LIVE — port 9008 (Gerçek Emirler, 9086 nginx proxy)
set -euo pipefail
cd "$(dirname "$0")"
exec ./.venv/bin/python binance_elite_pro_9008_live.py
