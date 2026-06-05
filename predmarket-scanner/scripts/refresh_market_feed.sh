#!/usr/bin/env bash
# Panel: Market Activity, YES/NO, feed, stream — data/recent_trades.pkl
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${PY:-./.venv/bin/python}"
exec "$PY" -c "from dashboard import _refresh_market_feed_sync; n=_refresh_market_feed_sync(); raise SystemExit(0 if n>0 else 1)"
