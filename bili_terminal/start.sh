#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="python3"
if [ -x "$ROOT_DIR/.venv/bin/python" ]; then
  PYTHON_BIN="$ROOT_DIR/.venv/bin/python"
fi

if [ "$#" -eq 0 ]; then
  exec "$PYTHON_BIN" -m bili_terminal tui
fi

case "$1" in
  textual|new-tui)
    shift
    exec "$PYTHON_BIN" -m bili_terminal.tui.app "$@"
    ;;
  legacy-tui)
    shift
    exec "$PYTHON_BIN" -m bili_terminal tui "$@"
    ;;
esac

exec "$PYTHON_BIN" -m bili_terminal "$@"
