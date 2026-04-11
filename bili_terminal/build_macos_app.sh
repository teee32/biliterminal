#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIST_DIR="${ROOT_DIR}/dist"
APP_NAME="BiliTerminal"
APP_BUNDLE="${DIST_DIR}/${APP_NAME}.app"
CONTENTS_DIR="${APP_BUNDLE}/Contents"
RESOURCES_DIR="${CONTENTS_DIR}/Resources"
PAYLOAD_DIR="${RESOURCES_DIR}/app/bili_terminal"
MACOS_DIR="${PAYLOAD_DIR}/macos"
HELPER_SOURCE="${ROOT_DIR}/bili_terminal/macos/biliterminal_audio_helper.m"
HELPER_BINARY="${PAYLOAD_DIR}/biliterminal-audio-helper"
ZIP_PATH="${DIST_DIR}/${APP_NAME}-macOS.zip"

copy_tree() {
    local source_dir="$1"
    local target_dir="$2"
    mkdir -p "${target_dir}"
    cp -R "${source_dir}/." "${target_dir}/"
}

rm -rf "${APP_BUNDLE}" "${ZIP_PATH}"
mkdir -p "${DIST_DIR}"

if ! command -v osacompile >/dev/null 2>&1; then
    echo "error: osacompile is required to build the macOS app bundle" >&2
    exit 1
fi

osacompile -o "${APP_BUNDLE}" "${ROOT_DIR}/bili_terminal/macos/BiliTerminal.applescript"

mkdir -p "${RESOURCES_DIR}" "${PAYLOAD_DIR}" "${MACOS_DIR}"
cp "${ROOT_DIR}/bili_terminal/macos/launch.command" "${RESOURCES_DIR}/launch.command"
chmod +x "${RESOURCES_DIR}/launch.command"

cp "${ROOT_DIR}/bili_terminal/__init__.py" "${PAYLOAD_DIR}/__init__.py"
cp "${ROOT_DIR}/bili_terminal/__main__.py" "${PAYLOAD_DIR}/__main__.py"
cp "${ROOT_DIR}/bili_terminal/bilibili_cli.py" "${PAYLOAD_DIR}/bilibili_cli.py"
copy_tree "${ROOT_DIR}/bili_terminal/tui" "${PAYLOAD_DIR}/tui"
cp "${HELPER_SOURCE}" "${MACOS_DIR}/biliterminal_audio_helper.m"

if command -v clang >/dev/null 2>&1; then
    if clang -fobjc-arc -framework Foundation -framework AVFoundation "${HELPER_SOURCE}" -o "${HELPER_BINARY}"; then
        chmod +x "${HELPER_BINARY}"
    else
        echo "warning: failed to compile macOS audio helper, runtime will try to build it later" >&2
    fi
else
    echo "warning: clang not found, runtime will try to build macOS audio helper later" >&2
fi

find "${APP_BUNDLE}" -name "__pycache__" -type d -prune -exec rm -rf {} +
find "${APP_BUNDLE}" -name "*.pyc" -delete

ditto -c -k --sequesterRsrc --keepParent "${APP_BUNDLE}" "${ZIP_PATH}"

printf 'Built %s\n' "${APP_BUNDLE}"
printf 'Packed %s\n' "${ZIP_PATH}"
