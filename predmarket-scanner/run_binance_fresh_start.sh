#!/usr/bin/env bash
# Binance Futures — sıfırdan başlat (DB sıfırla + yeni zeka modülleri)
set -euo pipefail
cd "$(dirname "$0")"
export BN_FUT_FRESH_START=1
export BN_FUT_REFRESH_DB=1
exec ./run_binance_futures_demo.sh
