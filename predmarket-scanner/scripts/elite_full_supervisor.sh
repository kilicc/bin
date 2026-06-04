#!/usr/bin/env bash
# Full stack supervisor — 9005/9006/9007 health + auto-restart
set -euo pipefail

_ctl_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${_ctl_dir}/.." && pwd)"
cd "$ROOT"

# shellcheck disable=SC1091
source scripts/elite_9005_mainnet_process_ctl.sh
# shellcheck disable=SC1091
source scripts/elite_9006_process_ctl.sh
# shellcheck disable=SC1091
source scripts/elite_9007_process_ctl.sh

SUP_PID_FILE=".pids/elite_full_supervisor.pid"
LOG="logs/elite_full_supervisor.log"
INTERVAL="${ELITE_FULL_SUPERVISOR_SEC:-45}"
STALE_SEC="${ELITE_FULL_HEARTBEAT_STALE_SEC:-120}"

_check_port() {
  local port="$1" label="$2"
  if curl -sf -m 8 "http://127.0.0.1:${port}/api/connection/live" >/dev/null 2>&1; then
    return 0
  fi
  if curl -sf -m 8 "http://127.0.0.1:${port}/api/paper/mega/snapshot?light=1" >/dev/null 2>&1; then
    return 0
  fi
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] ${label} port ${port} unhealthy" >>"${LOG}"
  return 1
}

_restart_if_needed() {
  local port="$1" restart_fn="$2" label="$3"
  if _check_port "${port}" "${label}"; then
    return 0
  fi
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] restarting ${label}" >>"${LOG}"
  "${restart_fn}" >>"${LOG}" 2>&1 || true
}

_supervisor_loop() {
  mkdir -p .pids logs
  echo $$ >"${SUP_PID_FILE}"
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] full supervisor başladı" >>"${LOG}"

  while true; do
    _restart_if_needed 9005 elite_9005_mainnet_restart "9005" || true
    _restart_if_needed 9006 elite_9006_restart "9006" || true
    _restart_if_needed 9007 elite_9007_restart "9007" || true
    sleep "${INTERVAL}"
  done
}

_supervisor_stop() {
  if [[ -f "${SUP_PID_FILE}" ]]; then
    local spid
    spid=$(cat "${SUP_PID_FILE}" 2>/dev/null || true)
    [[ -n "${spid}" ]] && kill "${spid}" 2>/dev/null || true
    rm -f "${SUP_PID_FILE}"
  fi
}

cmd="${1:-start}"
case "${cmd}" in
  start)
    if [[ -f "${SUP_PID_FILE}" ]] && kill -0 "$(cat "${SUP_PID_FILE}")" 2>/dev/null; then
      echo "Full supervisor zaten çalışıyor"
      exit 0
    fi
    nohup bash "$0" run >>"${LOG}" 2>&1 &
    echo $! >"${SUP_PID_FILE}"
    echo "✅ Full supervisor PID $(cat "${SUP_PID_FILE}")"
    ;;
  run) _supervisor_loop ;;
  stop) _supervisor_stop; echo "Full supervisor durduruldu" ;;
  status)
    if [[ -f "${SUP_PID_FILE}" ]] && kill -0 "$(cat "${SUP_PID_FILE}")" 2>/dev/null; then
      echo "Full supervisor: çalışıyor"
    else
      echo "Full supervisor: kapalı"
    fi
    elite_9005_mainnet_status || true
    elite_9006_status || true
    elite_9007_status || true
    ;;
  *)
    echo "Kullanım: $0 {start|stop|status|run}"
    exit 1
    ;;
esac
