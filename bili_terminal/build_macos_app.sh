#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIST_DIR="${ROOT_DIR}/dist"
APP_NAME="BiliTerminal"
APP_BUNDLE="${DIST_DIR}/${APP_NAME}.app"
CONTENTS_DIR="${APP_BUNDLE}/Contents"
RESOURCES_DIR="${CONTENTS_DIR}/Resources"
PAYLOAD_DIR="${RESOURCES_DIR}/app/bili_terminal"
ZIP_PATH="${DIST_DIR}/${APP_NAME}-macOS.zip"

rm -rf "${APP_BUNDLE}" "${ZIP_PATH}"
mkdir -p "${DIST_DIR}"

if ! command -v osacompile >/dev/null 2>&1; then
    echo "error: osacompile is required to build the macOS app bundle" >&2
    exit 1
fi

osacompile -o "${APP_BUNDLE}" "${ROOT_DIR}/bili_terminal/macos/BiliTerminal.applescript"

mkdir -p "${RESOURCES_DIR}" "${PAYLOAD_DIR}"
cp "${ROOT_DIR}/bili_terminal/macos/launch.command" "${RESOURCES_DIR}/launch.command"
chmod +x "${RESOURCES_DIR}/launch.command"

cp "${ROOT_DIR}/bili_terminal/__init__.py" "${PAYLOAD_DIR}/__init__.py"
cp "${ROOT_DIR}/bili_terminal/__main__.py" "${PAYLOAD_DIR}/__main__.py"
cp "${ROOT_DIR}/bili_terminal/bilibili_cli.py" "${PAYLOAD_DIR}/bilibili_cli.py"

find "${APP_BUNDLE}" -name "__pycache__" -type d -prune -exec rm -rf {} +
find "${APP_BUNDLE}" -name "*.pyc" -delete

ditto -c -k --sequesterRsrc --keepParent "${APP_BUNDLE}" "${ZIP_PATH}"

printf 'Built %s\n' "${APP_BUNDLE}"
printf 'Packed %s\n' "${ZIP_PATH}"
