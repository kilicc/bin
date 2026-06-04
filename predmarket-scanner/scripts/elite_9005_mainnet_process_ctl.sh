#!/usr/bin/env bash
# Elite 9005 MAINNET — tek örnek, port temizliği, güvenli start/stop/restart
set -euo pipefail

_ctl_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${_ctl_dir}/.." && pwd)"
cd "$ROOT"

PORT="${ELITE_9005_PORT:-9005}"
PID_DIR=".pids"
PID_FILE="${PID_DIR}/binance_elite_9005_mainnet.pid"
START_LOCK="${PID_DIR}/elite_9005_mainnet_start.lock"
PROC_PATTERN="binance_elite_pro_9005_mainnet.py"
RUN_SH="${ROOT}/run_binance_elite_9005_mainnet.sh"
PY="${PY:-./.venv/bin/python}"

_listen_pids() {
  if ! command -v lsof >/dev/null 2>&1; then
    return 0
  fi
  lsof -nP -iTCP:"${PORT}" -sTCP:LISTEN -t 2>/dev/null || true
}

_proc_pids() {
  pgrep -f "${PROC_PATTERN}" 2>/dev/null || true
}

elite_9005_mainnet_stop() {
  local force="${1:-0}"
  mkdir -p "${PID_DIR}"

  echo "  ⏹ Elite 9005 MAINNET durduruluyor (port ${PORT})..."

  if [[ -f "${PID_FILE}" ]]; then
    local pid
    pid=$(cat "${PID_FILE}" 2>/dev/null || true)
    if [[ -n "${pid}" ]] && kill -0 "${pid}" 2>/dev/null; then
      kill "${pid}" 2>/dev/null || true
    fi
    rm -f "${PID_FILE}"
  fi

  local pids
  pids=$(_proc_pids)
  if [[ -n "${pids}" ]]; then
    if [[ "${force}" == "1" ]]; then
      kill -9 ${pids} 2>/dev/null || true
    else
      kill ${pids} 2>/dev/null || true
      sleep 2
      pids=$(_proc_pids)
      [[ -n "${pids}" ]] && kill -9 ${pids} 2>/dev/null || true
    fi
  fi

  local listen
  listen=$(_listen_pids)
  if [[ -n "${listen}" ]]; then
    if [[ "${force}" == "1" ]]; then
      kill -9 ${listen} 2>/dev/null || true
    else
      kill ${listen} 2>/dev/null || true
      sleep 1
      listen=$(_listen_pids)
      [[ -n "${listen}" ]] && kill -9 ${listen} 2>/dev/null || true
    fi
  fi

  rm -f "${START_LOCK}" "${PID_DIR}/elite_instance_9005.lock"
  for i in $(seq 1 20); do
    if [[ -z "$(_listen_pids)" ]] && [[ -z "$(_proc_pids)" ]]; then
      echo "  ✓ Port ${PORT} boş, süreç yok"
      return 0
    fi
    sleep 1
  done
  echo "  ✗ Port ${PORT} hâlâ meşgul" >&2
  return 1
}

elite_9005_mainnet_wait_healthy() {
  local pid="${1:-}"
  local i
  for i in $(seq 1 45); do
    if [[ -n "${pid}" ]] && ! kill -0 "${pid}" 2>/dev/null; then
      echo "  ✗ Süreç ${pid} erken çıktı" >&2
      return 1
    fi
    if curl -sf -m 3 "http://127.0.0.1:${PORT}/api/connection/live" >/dev/null 2>&1; then
      echo "  ✓ Sağlık OK (http://127.0.0.1:${PORT})"
      return 0
    fi
    sleep 1
  done
  echo "  ⚠ Sağlık kontrolü zaman aşımı" >&2
  return 0
}

elite_9005_mainnet_status() {
  mkdir -p "${PID_DIR}"
  local listen proc pid_file_pid
  listen=$(_listen_pids)
  proc=$(_proc_pids)
  pid_file_pid=""
  [[ -f "${PID_FILE}" ]] && pid_file_pid=$(cat "${PID_FILE}" 2>/dev/null || true)

  echo "Elite 9005 MAINNET — port ${PORT}"
  echo "  PID dosyası: ${pid_file_pid:-—}"
  echo "  LISTEN: ${listen:-—}"
  echo "  mainnet launcher: ${proc:-—}"

  if [[ -n "${listen}" ]] || [[ -n "${proc}" ]]; then
    if curl -sf -m 4 "http://127.0.0.1:${PORT}/api/connection/live" >/dev/null 2>&1; then
      echo "  API: OK"
      return 0
    fi
    echo "  API: yanıt yok / yavaş"
    return 2
  fi
  echo "  Durum: kapalı"
  return 1
}

elite_9005_mainnet_start_locked() {
  mkdir -p "${PID_DIR}"

  if [[ -f "${START_LOCK}" ]]; then
    local lock_pid
    lock_pid=$(cat "${START_LOCK}" 2>/dev/null || true)
    if [[ -n "${lock_pid}" ]] && kill -0 "${lock_pid}" 2>/dev/null; then
      echo "✗ Başka bir start/restart işlemi sürüyor (PID ${lock_pid})" >&2
      exit 1
    fi
    rm -f "${START_LOCK}"
  fi
  echo $$ >"${START_LOCK}"
  # shellcheck disable=SC2064
  trap "rm -f '${START_LOCK}'" EXIT

  if [[ -n "$(_listen_pids)" ]] || [[ -n "$(_proc_pids)" ]]; then
    echo "✗ Port ${PORT} veya süreç zaten aktif — önce stop" >&2
    elite_9005_mainnet_status || true
    exit 1
  fi

  if [[ ! -x "${RUN_SH}" ]]; then
    chmod +x "${RUN_SH}" 2>/dev/null || true
  fi
  if [[ ! -f "${RUN_SH}" ]]; then
    echo "✗ run script yok: ${RUN_SH}" >&2
    exit 1
  fi

  bash "${RUN_SH}"
  local pid
  sleep 2
  pid=$(cat "${PID_FILE}" 2>/dev/null || true)
  elite_9005_mainnet_wait_healthy "${pid}"
}

elite_9005_mainnet_restart() {
  elite_9005_mainnet_stop 0 || elite_9005_mainnet_stop 1
  elite_9005_mainnet_start_locked
}

cmd="${1:-status}"
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  case "${cmd}" in
    stop) elite_9005_mainnet_stop 0 ;;
    force-stop) elite_9005_mainnet_stop 1 ;;
    start) elite_9005_mainnet_start_locked ;;
    restart) elite_9005_mainnet_restart ;;
    status) elite_9005_mainnet_status ;;
    *)
      echo "Kullanım: $0 {status|stop|force-stop|start|restart}"
      exit 1
      ;;
  esac
fi
