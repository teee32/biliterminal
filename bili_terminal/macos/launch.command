#!/usr/bin/env bash
set -euo pipefail

APP_RESOURCES_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PAYLOAD_DIR="${APP_RESOURCES_DIR}/app"
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH:-}"
export BILITERMINAL_HOME="${BILITERMINAL_HOME:-${HOME}/.biliterminal}"
export PYTHONPYCACHEPREFIX="${PYTHONPYCACHEPREFIX:-${BILITERMINAL_HOME}/pycache}"
LOG_FILE="${BILITERMINAL_LOG_FILE:-${BILITERMINAL_HOME}/launcher.log}"

mkdir -p "${BILITERMINAL_HOME}" "${PYTHONPYCACHEPREFIX}" "$(dirname "${LOG_FILE}")"
printf '[%s] launch.command invoked\n' "$(date '+%Y-%m-%d %H:%M:%S')" >> "${LOG_FILE}"

PYTHON_BIN=""
for candidate in "${BILITERMINAL_PYTHON:-}" python3 /opt/homebrew/bin/python3 /usr/local/bin/python3; do
    if [ -n "${candidate}" ] && command -v "${candidate}" >/dev/null 2>&1; then
        PYTHON_BIN="$(command -v "${candidate}")"
        break
    fi
done

if [ -z "${PYTHON_BIN}" ]; then
    printf '[%s] python3 not found\n' "$(date '+%Y-%m-%d %H:%M:%S')" >> "${LOG_FILE}"
    /usr/bin/osascript -e 'display dialog "未找到 python3，请先安装 Python 3 后再运行 BiliTerminal。" buttons {"好"} default button 1 with icon stop'
    exit 1
fi

printf '[%s] using python: %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "${PYTHON_BIN}" >> "${LOG_FILE}"

cd "${PAYLOAD_DIR}"
clear
printf 'BiliTerminal 正在启动...\n\n'
"${PYTHON_BIN}" -m bili_terminal tui
STATUS=$?
printf '[%s] tui exited with status: %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "${STATUS}" >> "${LOG_FILE}"
exit "${STATUS}"
