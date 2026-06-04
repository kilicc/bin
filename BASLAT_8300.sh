#!/usr/bin/env bash
# Elite APEX 8300 — binancex kopyasından başlat
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/predmarket-scanner" && pwd)"
cd "$ROOT"
exec ./run_elite_apex_2x_8300.sh "$@"
