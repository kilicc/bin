#!/usr/bin/env bash
# MEGA mainnet — port 9006 (GCP prod, fapi.binance.com)
set -euo pipefail
cd "$(dirname "$0")"
exec ./.venv/bin/python binance_elite_pro_9006_mainnet.py
