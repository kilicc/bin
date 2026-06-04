#!/usr/bin/env bash
# Go-live doğrulama — full stack (9005 + 9006 + 9007 + Lab + Vertex)
set -euo pipefail

PANEL_URL_9007="${1:-}"
AUTH="${PANEL_AUTH:-}"
CURL_AUTH=()
if [[ -n "${AUTH}" ]]; then
  CURL_AUTH=(-u "${AUTH}")
fi

fail=0
ok() { echo "  OK  $*"; }
bad() { echo "  FAIL $*"; fail=1; }
warn() { echo "  WARN $*"; }

echo "=== GCP Full Stack Go-Live Check ==="

echo ""
echo "[1] Binance mainnet ping"
if curl -sf -m 5 "https://fapi.binance.com/fapi/v1/ping" >/dev/null; then
  ok "fapi.binance.com reachable"
else
  bad "fapi.binance.com unreachable"
fi

_check_bot() {
  local port="$1" label="$2"
  echo ""
  echo "[${label}] port ${port}"
  if curl -sf -m 8 "${CURL_AUTH[@]}" "http://127.0.0.1:${port}/api/connection/live" >/dev/null 2>&1; then
    ok "${label} /api/connection/live"
  elif curl -sf -m 12 "${CURL_AUTH[@]}" "http://127.0.0.1:${port}/api/paper/mega/snapshot?light=1" >/dev/null 2>&1; then
    ok "${label} /api/paper/mega/snapshot"
  else
    bad "${label} API unreachable"
  fi
  if command -v ss >/dev/null 2>&1; then
    if ss -lntp 2>/dev/null | grep ":${port}" | grep -q "127.0.0.1:${port}"; then
      ok "${label} binds 127.0.0.1 only"
    elif ss -lntp 2>/dev/null | grep -q ":${port}"; then
      echo "  WARN ${label} may be exposed publicly"
    fi
  fi
}

_check_bot 9005 "9005 BERSERK2"
_check_bot 9006 "9006 MEGA"
_check_bot 9007 "9007 MEGA+Lab"

echo ""
echo "[Lab] LLM health (9007)"
if curl -sf -m 15 "${CURL_AUTH[@]}" "http://127.0.0.1:9007/api/health/strip" | grep -q '"llm"'; then
  ok "/api/health/strip includes llm"
  llm_ok=$(curl -sf -m 20 "${CURL_AUTH[@]}" "http://127.0.0.1:9007/api/health/strip" 2>/dev/null | grep -o '"ok":[^,]*' | head -1 || true)
  echo "  LLM strip: ${llm_ok:-unknown}"
else
  bad "/api/health/strip"
fi

echo ""
echo "[Lab] sessions endpoint"
if curl -sf -m 10 "${CURL_AUTH[@]}" "http://127.0.0.1:9007/api/lab/sessions" >/dev/null 2>&1; then
  ok "/api/lab/sessions"
else
  bad "/api/lab/sessions"
fi

if [[ -n "${PANEL_URL_9007}" ]]; then
  echo ""
  echo "[nginx] HTTPS panel 9007"
  code=$(curl -s -o /dev/null -w "%{http_code}" "${CURL_AUTH[@]}" -m 15 "${PANEL_URL_9007}/api/health/strip" || echo 000)
  if [[ "${code}" == "200" ]]; then
    ok "panel HTTP ${code}"
  else
    bad "panel HTTP ${code} (PANEL_AUTH=user:pass)"
  fi
fi

echo ""
echo "[systemd] services"
for svc in binance-elite-9005-mainnet binance-elite-9006-mainnet binance-elite-9007-mainnet elite-full-supervisor; do
  if systemctl is-active --quiet "${svc}" 2>/dev/null; then
    ok "${svc} active"
  else
    bad "${svc} not active"
  fi
done

echo ""
echo "[data] protected files"
for f in \
  data/binance_elite_8300_9005_state.db \
  data/lab_9007/lessons.jsonl \
  data/mega_9007; do
  if [[ -e "${f}" ]]; then
    ok "${f} exists"
  else
    warn "${f} missing (yeni kurulum olabilir)"
  fi
done

echo ""
if [[ "${fail}" -eq 0 ]]; then
  echo "=== GO-LIVE: PASS ==="
else
  echo "=== GO-LIVE: FAIL ==="
  exit 1
fi
