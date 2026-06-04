#!/usr/bin/env bash
# Elite 9005 — süreç ölürse veya API/heartbeat donarsa otomatik yeniden başlat
set -euo pipefail

_ctl_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${_ctl_dir}/.." && pwd)"
cd "$ROOT"

# shellcheck disable=SC1091
source scripts/elite_9005_process_ctl.sh

PORT="${ELITE_9005_PORT:-9005}"
PID_FILE=".pids/binance_elite_8300_9005.pid"
HEARTBEAT=".pids/elite_9005_heartbeat.json"
SUP_PID_FILE=".pids/elite_9005_supervisor.pid"
LOG="logs/elite_9005_supervisor.log"
INTERVAL="${ELITE_9005_SUPERVISOR_SEC:-30}"
STALE_SEC="${ELITE_9005_HEARTBEAT_STALE_SEC:-90}"
RESTART_COOLDOWN_SEC="${ELITE_9005_RESTART_COOLDOWN_SEC:-120}"
MAX_RESTARTS_IN_WINDOW="${ELITE_9005_MAX_RESTARTS_IN_WINDOW:-3}"
RESTART_WINDOW_SEC="${ELITE_9005_RESTART_WINDOW_SEC:-120}"

if [[ "${ELITE_9005_MAINNET:-0}" == "1" ]]; then
  # shellcheck disable=SC1091
  source scripts/elite_9005_mainnet_process_ctl.sh
  PID_FILE=".pids/binance_elite_9005_mainnet.pid"
  elite_9005_restart() { elite_9005_mainnet_restart; }
  elite_9005_stop() { elite_9005_mainnet_stop "${1:-0}"; }
  elite_9005_status() { elite_9005_mainnet_status; }
fi

_supervisor_stop() {
  if [[ -f "${SUP_PID_FILE}" ]]; then
    local spid
    spid=$(cat "${SUP_PID_FILE}" 2>/dev/null || true)
    if [[ -n "${spid}" ]] && kill -0 "${spid}" 2>/dev/null; then
      kill "${spid}" 2>/dev/null || true
    fi
    rm -f "${SUP_PID_FILE}"
  fi
}

_supervisor_loop() {
  mkdir -p .pids logs
  echo $$ >"${SUP_PID_FILE}"
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] supervisor başladı (interval=${INTERVAL}s stale=${STALE_SEC}s)" >>"${LOG}"
  local restart_times=""

  while true; do
    local need_restart=0 reason=""

    if [[ ! -f "${PID_FILE}" ]]; then
      need_restart=1
      reason="pid dosyası yok"
    else
      local pid
      pid=$(cat "${PID_FILE}" 2>/dev/null || true)
      if [[ -z "${pid}" ]] || ! kill -0 "${pid}" 2>/dev/null; then
        need_restart=1
        reason="süreç ölü (pid=${pid:-?})"
      elif ! curl -sf -m 5 "http://127.0.0.1:${PORT}/api/connection/live" >/dev/null 2>&1; then
        need_restart=1
        reason="API yanıt yok"
      elif [[ -f "${HEARTBEAT}" ]]; then
        local stale
        stale=$("${PY:-./.venv/bin/python}" - <<'PY' 2>/dev/null || echo 0
import json, time, sys
from pathlib import Path
p = Path(".pids/elite_9005_heartbeat.json")
try:
    d = json.loads(p.read_text())
    print(int(time.time() - float(d.get("ts") or 0)))
except Exception:
    print(9999)
PY
)
        if [[ "${stale}" -gt "${STALE_SEC}" ]]; then
          need_restart=1
          reason="heartbeat eski (${stale}s)"
        fi
      fi
    fi

    if [[ "${need_restart}" == "1" ]]; then
      local now_ts
      now_ts=$(date +%s)
      local recent=""
      for ts in ${restart_times}; do
        if [[ -n "${ts}" ]] && (( now_ts - ts < RESTART_WINDOW_SEC )); then
          recent="${recent} ${ts}"
        fi
      done
      restart_times="${recent}"
      local recent_count=0
      for _ in ${restart_times}; do
        recent_count=$((recent_count + 1))
      done
      if [[ "${recent_count}" -ge "${MAX_RESTARTS_IN_WINDOW}" ]]; then
        echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] restart fırtınası — ${RESTART_COOLDOWN_SEC}s bekleniyor (${reason})" >>"${LOG}"
        sleep "${RESTART_COOLDOWN_SEC}"
        restart_times=""
      fi
      echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] yeniden başlat: ${reason}" >>"${LOG}"
      elite_9005_restart >>"${LOG}" 2>&1 || elite_9005_stop 1 >>"${LOG}" 2>&1 || true
      restart_times="${restart_times} ${now_ts}"
      sleep 5
    fi

    sleep "${INTERVAL}"
  done
}

cmd="${1:-start}"
case "${cmd}" in
  start)
    if [[ -f "${SUP_PID_FILE}" ]]; then
      spid=$(cat "${SUP_PID_FILE}" 2>/dev/null || true)
      if [[ -n "${spid}" ]] && kill -0 "${spid}" 2>/dev/null; then
        echo "Supervisor zaten çalışıyor (PID ${spid})"
        exit 0
      fi
    fi
    nohup bash "$0" loop >>"${LOG}" 2>&1 &
    echo $! >"${SUP_PID_FILE}"
    echo "✅ Supervisor PID $(cat "${SUP_PID_FILE}") | log: ${LOG}"
    ;;
  run) _supervisor_loop ;;
  loop) _supervisor_loop ;;
  stop) _supervisor_stop; echo "Supervisor durduruldu" ;;
  status)
    if [[ -f "${SUP_PID_FILE}" ]] && kill -0 "$(cat "${SUP_PID_FILE}")" 2>/dev/null; then
      echo "Supervisor: çalışıyor (PID $(cat "${SUP_PID_FILE}"))"
    else
      echo "Supervisor: kapalı"
    fi
    elite_9005_status || true
    ;;
  *)
    echo "Kullanım: $0 {start|stop|status}"
    exit 1
    ;;
esac
