#!/usr/bin/env bash
# MEGA mainnet — port 9007 (GCP prod, Admin+Lab, fapi.binance.com)
set -euo pipefail
cd "$(dirname "$0")"
exec ./.venv/bin/python binance_elite_pro_9007_mainnet.py
