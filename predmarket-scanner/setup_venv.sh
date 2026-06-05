#!/usr/bin/env bash
# Bu Mac'te venv kurulumu — python3.10+ tercih (canlı CLOB için)
set -euo pipefail
cd "$(dirname "$0")"

pick_python() {
  for cmd in python3.12 python3.11 python3.10 python3 /usr/bin/python3; do
    if command -v "$cmd" >/dev/null 2>&1; then
      ver=$("$cmd" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null) || continue
      major=${ver%%.*}
      minor=${ver#*.}
      if [[ "$major" -eq 3 && "$minor" -ge 10 ]]; then
        echo "$cmd"
        return 0
      fi
      if [[ "$major" -eq 3 && "$minor" -ge 9 ]]; then
        FALLBACK="$cmd"
      fi
    fi
  done
  if [[ -n "${FALLBACK:-}" ]]; then
    echo "$FALLBACK"
    return 0
  fi
  return 1
}

PY=$(pick_python) || {
  echo "Python 3 bulunamadı."
  echo "  Kurulum: https://www.python.org/downloads/ (3.12 önerilir)"
  echo "  veya: xcode-select --install  ardından python3"
  exit 1
}

echo "Python: $PY ($($PY --version 2>&1))"
rm -rf .venv
"$PY" -m venv .venv
./.venv/bin/pip install -U pip

VER=$(./.venv/bin/python -c "import sys; print(sys.version_info.minor)")
if ./.venv/bin/python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)"; then
  ./.venv/bin/pip install -r requirements.txt
  echo "Tam kurulum (py-clob-client-v2 dahil)."
else
  echo "Uyarı: Python 3.$VER — py-clob-client-v2 için 3.10+ gerekir."
  echo "Paper/dashboard için temel paketler kuruluyor…"
  ./.venv/bin/pip install httpx pydantic anthropic python-dotenv rich typer fastapi 'uvicorn[standard]'
  echo "Canlı emir için Python 3.12 kurup bu scripti tekrar çalıştırın."
fi

echo ""
echo "Kullanım:"
echo "  source .venv/bin/activate"
echo "  python connection_check.py"
