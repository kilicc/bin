#!/usr/bin/env bash
# MEGA 9006 — pozisyon worker / borsa API tıkanma izleyici
set -euo pipefail
PORT="${MEGA_PORT:-9006}"
INTERVAL="${MEGA_WATCH_SEC:-15}"
LOG="${MEGA_LOG:-logs/binance_elite_mega_9006.log}"

echo "MEGA API watch port=$PORT interval=${INTERVAL}s log=$LOG"
while true; do
  ts="$(date -u +%H:%M:%S)"
  hb="$(curl -s -m 4 "http://127.0.0.1:${PORT}/api/heartbeat" 2>/dev/null || echo '{}')"
  stalls="$(echo "$hb" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('position_stalls','?'), d.get('position_restarts','?'), d.get('position_tick_ms','?'))" 2>/dev/null || echo "? ? ?")"
  mega="$(echo "$hb" | python3 -c "
import json,sys
d=json.load(sys.stdin).get('mega') or {}
print('open', d.get('open'), 'tp', d.get('tp_armed'), 'exit_ms', d.get('last_exit_tick_ms'), 'cache_ms', d.get('cache_age_ms'), 'busy', d.get('snapshot_busy'))
" 2>/dev/null || echo "mega ?")"
  recent="$(grep -E 'döngü_gecikme|MEGA borsa TP|algo temizlik|stale 4s' "$LOG" 2>/dev/null | tail -3 | tr '\n' ' | ' || true)"
  echo "[$ts] stalls/restarts/tick_ms=$stalls | $mega"
  if [[ -n "$recent" ]]; then
    echo "  log: $recent"
  fi
  sleep "$INTERVAL"
done
