@echo off
setlocal enabledelayedexpansion

set "APP_DIR=%~dp0"
set "APP_DIR=%APP_DIR:~0,-1%"
set "RUNTIME_DIR=%APP_DIR%\runtime"
set "APP_EXECUTABLE=%RUNTIME_DIR%\BiliTerminal.exe"
set "PAYLOAD_DIR=%APP_DIR%\app"

if not defined BILITERMINAL_HOME set "BILITERMINAL_HOME=%USERPROFILE%\.biliterminal"
if not defined TERM set "TERM=xterm-256color"
if not defined COLORTERM set "COLORTERM=truecolor"

set "LOG_FILE=%BILITERMINAL_HOME%\launcher.log"

if not exist "%BILITERMINAL_HOME%" mkdir "%BILITERMINAL_HOME%"

>>"%LOG_FILE%" echo [%date% %time%] launch.bat invoked

if exist "%APP_EXECUTABLE%" (
    cls
    echo BiliTerminal 正在启动...
    echo.
    >>"%LOG_FILE%" echo [%date% %time%] launching bundled runtime
    "%APP_EXECUTABLE%" %*
    set "EXIT_CODE=!errorlevel!"
    >>"%LOG_FILE%" echo [%date% %time%] bundled runtime exited with status: !EXIT_CODE!
    exit /b !EXIT_CODE!
)

>>"%LOG_FILE%" echo [%date% %time%] bundled runtime missing, falling back to python module

set "PYTHON_BIN="
where python >nul 2>&1
if !errorlevel! equ 0 set "PYTHON_BIN=python"

if "%PYTHON_BIN%"=="" (
    >>"%LOG_FILE%" echo [%date% %time%] python not found
    echo 错误：未找到内置运行时，且系统里也没有 python，无法启动 BiliTerminal。
    pause
    exit /b 1
)

>>"%LOG_FILE%" echo [%date% %time%] using python fallback: %PYTHON_BIN%
cls
echo BiliTerminal 正在启动...
echo.
"%PYTHON_BIN%" -m bili_terminal --tui %*
set "EXIT_CODE=!errorlevel!"
>>"%LOG_FILE%" echo [%date% %time%] textual exited with status: !EXIT_CODE!
exit /b !EXIT_CODE!