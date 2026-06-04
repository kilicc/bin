#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
exec ./scripts/elite_9005_process_ctl.sh status
