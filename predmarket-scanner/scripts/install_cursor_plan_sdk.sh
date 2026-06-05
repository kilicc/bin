#!/usr/bin/env bash
# Cursor plan SDK — npm yoksa tarball ile kurulum
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/cursor-plan" && pwd)"
cd "$ROOT"
VER="${CURSOR_SDK_VERSION:-1.0.13}"
mkdir -p node_modules/@cursor
if [[ -d node_modules/@cursor/sdk/dist ]]; then
  echo "OK: @cursor/sdk zaten kurulu"
  exit 0
fi
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
curl -fsSL "https://registry.npmjs.org/@cursor/sdk/-/sdk-${VER}.tgz" -o "$TMP/sdk.tgz"
tar -xzf "$TMP/sdk.tgz" -C "$TMP"
rm -rf node_modules/@cursor/sdk
mv "$TMP/package" node_modules/@cursor/sdk
ARCH="$(uname -m)"
OS="$(uname -s | tr '[:upper:]' '[:lower:]')"
if [[ "$OS" == "darwin" && "$ARCH" == "arm64" ]]; then
  curl -fsSL "https://registry.npmjs.org/@cursor/sdk-darwin-arm64/-/sdk-darwin-arm64-${VER}.tgz" -o "$TMP/plat.tgz"
  tar -xzf "$TMP/plat.tgz" -C "$TMP"
  rm -rf node_modules/@cursor/sdk-darwin-arm64
  mv "$TMP/package" node_modules/@cursor/sdk-darwin-arm64
fi
echo "OK: @cursor/sdk ${VER} kuruldu → $ROOT/node_modules"
