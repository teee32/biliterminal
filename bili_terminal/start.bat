@echo off
setlocal enabledelayedexpansion

set "ROOT_DIR=%~dp0.."
cd /d "%ROOT_DIR%"

set "TERM=xterm-256color"
set "COLORTERM=truecolor"

set "PYTHON_BIN=python"
if exist "%ROOT_DIR%\.venv\Scripts\python.exe" (
    set "PYTHON_BIN=%ROOT_DIR%\.venv\Scripts\python.exe"
)

if "%~1"=="" (
    "%PYTHON_BIN%" -m bili_terminal --tui
    goto :eof
)

"%PYTHON_BIN%" -m bili_terminal %*
