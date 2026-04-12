#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIST_DIR="${ROOT_DIR}/dist"
BUILD_DIR="${ROOT_DIR}/build/macos-app"
APP_NAME="BiliTerminal"
APP_BUNDLE="${DIST_DIR}/${APP_NAME}.app"
CONTENTS_DIR="${APP_BUNDLE}/Contents"
RESOURCES_DIR="${CONTENTS_DIR}/Resources"
PAYLOAD_DIR="${RESOURCES_DIR}/app/bili_terminal"
MACOS_DIR="${PAYLOAD_DIR}/macos"
RUNTIME_STAGE_DIR="${BUILD_DIR}/pyinstaller-dist"
RUNTIME_WORK_DIR="${BUILD_DIR}/pyinstaller-work"
RUNTIME_SPEC_DIR="${BUILD_DIR}/pyinstaller-spec"
RUNTIME_SOURCE_DIR="${RUNTIME_STAGE_DIR}/${APP_NAME}"
RUNTIME_DIR="${RESOURCES_DIR}/runtime"
HELPER_SOURCE="${ROOT_DIR}/bili_terminal/macos/biliterminal_audio_helper.m"
HELPER_BINARY="${PAYLOAD_DIR}/biliterminal-audio-helper"
RUNTIME_HELPER_BINARY="${RUNTIME_DIR}/biliterminal-audio-helper"
ZIP_PATH="${DIST_DIR}/${APP_NAME}-macOS.zip"
PYTHON_BUILD_BIN=""

copy_tree() {
    local source_dir="$1"
    local target_dir="$2"
    mkdir -p "${target_dir}"
    cp -R "${source_dir}/." "${target_dir}/"
}

resolve_command() {
    local candidate=""
    for candidate in "$@"; do
        if [ -n "${candidate}" ] && command -v "${candidate}" >/dev/null 2>&1; then
            command -v "${candidate}"
            return 0
        fi
    done
    return 1
}

normalize_bundle_metadata() {
    "${PYTHON_BUILD_BIN}" - <<'PY' "${APP_BUNDLE}" "${ROOT_DIR}"
from __future__ import annotations

import plistlib
import sys
import tomllib
from pathlib import Path

bundle_path = Path(sys.argv[1])
root_dir = Path(sys.argv[2])
info_path = bundle_path / "Contents" / "Info.plist"
project = tomllib.loads((root_dir / "pyproject.toml").read_text(encoding="utf-8"))
version = str(project.get("project", {}).get("version", "0.0.0"))

if info_path.exists():
    with info_path.open("rb") as handle:
        info = plistlib.load(handle)
else:
    info = {}

info.update(
    {
        "CFBundleName": "BiliTerminal",
        "CFBundleDisplayName": "BiliTerminal",
        "CFBundleIdentifier": "io.github.teee32.biliterminal",
        "CFBundleShortVersionString": version,
        "CFBundleVersion": version,
        "NSHighResolutionCapable": True,
        "OSAAppletShowStartupScreen": False,
    }
)

for key in (
    "LSRequiresCarbon",
    "LSMinimumSystemVersionByArchitecture",
    "NSAppleEventsUsageDescription",
    "NSAppleMusicUsageDescription",
    "NSCalendarsUsageDescription",
    "NSCameraUsageDescription",
    "NSContactsUsageDescription",
    "NSHomeKitUsageDescription",
    "NSMicrophoneUsageDescription",
    "NSPhotoLibraryUsageDescription",
    "NSRemindersUsageDescription",
    "NSSiriUsageDescription",
    "NSSystemAdministrationUsageDescription",
):
    info.pop(key, None)

with info_path.open("wb") as handle:
    plistlib.dump(info, handle, sort_keys=True)
PY
}

sign_bundle() {
    codesign --force --deep --sign - "${APP_BUNDLE}"
    codesign --verify --deep --strict --verbose=2 "${APP_BUNDLE}"
}

run_bundle_smoke_test() {
    if [ "${BILITERMINAL_SKIP_SMOKE:-0}" = "1" ]; then
        printf 'Skipped smoke verification for %s\n' "${APP_BUNDLE}"
        return 0
    fi

    local smoke_home="${BUILD_DIR}/smoke-home"
    local smoke_log="${smoke_home}/launcher.log"
    local smoke_output="${BUILD_DIR}/smoke-launch.txt"

    rm -rf "${smoke_home}" "${smoke_output}"
    mkdir -p "${smoke_home}"

    TERM="${TERM:-xterm-256color}" \
    BILITERMINAL_HOME="${smoke_home}" \
    BILITERMINAL_LOG_FILE="${smoke_log}" \
    /bin/bash "${RESOURCES_DIR}/launch.command" --help >"${smoke_output}" 2>&1

    grep -q "usage: BiliTerminal" "${smoke_output}" || {
        echo "error: smoke verification did not reach bundled runtime help output" >&2
        cat "${smoke_output}" >&2
        exit 1
    }
    grep -q "bundled runtime exited with status: 0" "${smoke_log}" || {
        echo "error: bundled runtime success marker missing from smoke log" >&2
        cat "${smoke_log}" >&2
        exit 1
    }
    if grep -q "using python fallback" "${smoke_log}"; then
        echo "error: smoke verification unexpectedly used python fallback" >&2
        cat "${smoke_log}" >&2
        exit 1
    fi

    printf 'Smoke-verified %s\n' "${APP_BUNDLE}"
}

rm -rf "${APP_BUNDLE}" "${ZIP_PATH}" "${BUILD_DIR}"
mkdir -p "${DIST_DIR}" "${BUILD_DIR}"

PYINSTALLER_BIN="$(resolve_command "${BILITERMINAL_PYINSTALLER:-}" "${ROOT_DIR}/.venv/bin/pyinstaller" pyinstaller)" || {
    echo "error: pyinstaller is required to build a standalone macOS app bundle" >&2
    echo "hint: python3 -m pip install -e '.[build]'" >&2
    exit 1
}
PYTHON_BUILD_BIN="$(resolve_command "${BILITERMINAL_BUILD_PYTHON:-}" "${ROOT_DIR}/.venv/bin/python" python3)" || {
    echo "error: python3 is required to finalize the macOS app bundle" >&2
    exit 1
}

if ! command -v osacompile >/dev/null 2>&1; then
    echo "error: osacompile is required to build the macOS app bundle" >&2
    exit 1
fi

if ! command -v ditto >/dev/null 2>&1; then
    echo "error: ditto is required to package the macOS app bundle" >&2
    exit 1
fi
if ! command -v codesign >/dev/null 2>&1; then
    echo "error: codesign is required to finalize the macOS app bundle" >&2
    exit 1
fi

"${PYINSTALLER_BIN}" \
    --noconfirm \
    --clean \
    --onedir \
    --console \
    --name "${APP_NAME}" \
    --distpath "${RUNTIME_STAGE_DIR}" \
    --workpath "${RUNTIME_WORK_DIR}" \
    --specpath "${RUNTIME_SPEC_DIR}" \
    --paths "${ROOT_DIR}" \
    --collect-data bili_terminal \
    "${ROOT_DIR}/bili_terminal/macos/runtime_entry.py"

if [ ! -x "${RUNTIME_SOURCE_DIR}/${APP_NAME}" ]; then
    echo "error: bundled runtime was not produced at ${RUNTIME_SOURCE_DIR}/${APP_NAME}" >&2
    exit 1
fi

osacompile -o "${APP_BUNDLE}" "${ROOT_DIR}/bili_terminal/macos/BiliTerminal.applescript"
normalize_bundle_metadata

mkdir -p "${RESOURCES_DIR}" "${PAYLOAD_DIR}" "${MACOS_DIR}" "${RUNTIME_DIR}"
cp "${ROOT_DIR}/bili_terminal/macos/launch.command" "${RESOURCES_DIR}/launch.command"
chmod +x "${RESOURCES_DIR}/launch.command"

cp "${ROOT_DIR}/bili_terminal/__init__.py" "${PAYLOAD_DIR}/__init__.py"
cp "${ROOT_DIR}/bili_terminal/__main__.py" "${PAYLOAD_DIR}/__main__.py"
cp "${ROOT_DIR}/bili_terminal/bilibili_cli.py" "${PAYLOAD_DIR}/bilibili_cli.py"
copy_tree "${ROOT_DIR}/bili_terminal/tui" "${PAYLOAD_DIR}/tui"
copy_tree "${RUNTIME_SOURCE_DIR}" "${RUNTIME_DIR}"
cp "${HELPER_SOURCE}" "${MACOS_DIR}/biliterminal_audio_helper.m"
cp "${HELPER_SOURCE}" "${RUNTIME_DIR}/biliterminal_audio_helper.m"

if command -v clang >/dev/null 2>&1; then
    if clang -fobjc-arc -framework Foundation -framework AVFoundation "${HELPER_SOURCE}" -o "${HELPER_BINARY}"; then
        chmod +x "${HELPER_BINARY}"
        cp "${HELPER_BINARY}" "${RUNTIME_HELPER_BINARY}"
        chmod +x "${RUNTIME_HELPER_BINARY}"
    else
        echo "warning: failed to compile macOS audio helper, runtime will try to build it later" >&2
    fi
else
    echo "warning: clang not found, runtime will try to build macOS audio helper later" >&2
fi

find "${APP_BUNDLE}" -name "__pycache__" -type d -prune -exec rm -rf {} +
find "${APP_BUNDLE}" -name "*.pyc" -delete

sign_bundle
run_bundle_smoke_test
ditto -c -k --sequesterRsrc --keepParent "${APP_BUNDLE}" "${ZIP_PATH}"

printf 'Built %s\n' "${APP_BUNDLE}"
printf 'Packed %s\n' "${ZIP_PATH}"
