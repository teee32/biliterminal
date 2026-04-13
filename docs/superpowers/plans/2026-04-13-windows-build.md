# Windows Build Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a PowerShell build script and Windows launcher that produce a self-contained BiliTerminal distribution for Windows, mirroring the macOS build pipeline.

**Architecture:** PyInstaller bundles the Python runtime into `runtime/BiliTerminal/`. A `launch.bat` launcher prefers the bundled runtime, falls back to system Python. Source payload is copied into `app/bili_terminal/`. Final output is a zip archive.

**Tech Stack:** PowerShell 5.1+, PyInstaller 6+, Python 3.11+

---

## File Structure

| Action | Path | Purpose |
|--------|------|---------|
| Create | `bili_terminal/windows/runtime_entry.py` | PyInstaller entry point (same logic as macos version) |
| Create | `bili_terminal/windows/launch.bat` | Windows launcher (mirrors macos/launch.command) |
| Create | `build_windows_app.ps1` | Main build script (mirrors build_macos_app.sh) |

---

### Task 1: Create `bili_terminal/windows/runtime_entry.py`

**Files:**
- Create: `bili_terminal/windows/runtime_entry.py`

- [ ] **Step 1: Create the runtime entry point**

This file is identical in logic to `bili_terminal/macos/runtime_entry.py` — it exists so PyInstaller can target a platform-specific entry point.

```python
from __future__ import annotations

import sys

from bili_terminal.__main__ import main


def run() -> int:
    args = sys.argv[1:] or ["--tui"]
    return main(args)


if __name__ == "__main__":
    raise SystemExit(run())
```

- [ ] **Step 2: Verify it runs**

Run: `python -c "from bili_terminal.windows.runtime_entry import run; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add bili_terminal/windows/runtime_entry.py bili_terminal/windows/__init__.py
git commit -m "feat: add Windows runtime entry point for PyInstaller"
```

---

### Task 2: Create `bili_terminal/windows/launch.bat`

**Files:**
- Create: `bili_terminal/windows/launch.bat`

- [ ] **Step 1: Create the Windows launcher**

This mirrors `bili_terminal/macos/launch.command`. It prefers the bundled PyInstaller runtime, falls back to system Python.

```bat
@echo off
setlocal enabledelayedexpansion

set "APP_DIR=%~dp0"
set "APP_DIR=%APP_DIR:~0,-1%"
set "RUNTIME_DIR=%APP_DIR%\runtime\BiliTerminal"
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
```

- [ ] **Step 2: Test launch.bat with --help (requires PyInstaller build first; can be tested manually after full build)**

Manual test after full build: `launch.bat --help`
Expected: Output contains `usage: BiliTerminal`

- [ ] **Step 3: Commit**

```bash
git add bili_terminal/windows/launch.bat
git commit -m "feat: add Windows launch.bat launcher for bundled runtime"
```

---

### Task 3: Create `build_windows_app.ps1`

**Files:**
- Create: `build_windows_app.ps1`

This is the main build script. It mirrors `build_macos_app.sh` step by step.

- [ ] **Step 1: Write the build script**

```powershell
#Requires -Version 5.1
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

$RootDir = Resolve-Path (Join-Path $PSScriptRoot '.')
$DistDir = Join-Path $RootDir 'dist'
$BuildDir = Join-Path $RootDir 'build\windows-app'
$AppName = 'BiliTerminal'
$AppDir = Join-Path $DistDir $AppName
$PayloadDir = Join-Path $AppDir 'app\bili_terminal'
$RuntimeStageDir = Join-Path $BuildDir 'pyinstaller-dist'
$RuntimeWorkDir = Join-Path $BuildDir 'pyinstaller-work'
$RuntimeSpecDir = Join-Path $BuildDir 'pyinstaller-spec'
$RuntimeSourceDir = Join-Path $RuntimeStageDir $AppName
$RuntimeDir = Join-Path $AppDir 'runtime'
$ZipPath = Join-Path $DistDir "$AppName-Windows.zip"
$WindowsDir = Join-Path $RootDir 'bili_terminal\windows'

function Copy-Tree {
    param([string]$Source, [string]$Target)
    if (-not (Test-Path $Target)) { New-Item -ItemType Directory -Path $Target -Force | Out-Null }
    Get-ChildItem -Path $Source | Copy-Item -Destination $Target -Recurse -Force
}

function Resolve-Command {
    param([string[]]$Candidates)
    foreach ($c in $Candidates) {
        if ($c -and (Get-Command $c -ErrorAction SilentlyContinue)) {
            return (Get-Command $c).Source
        }
    }
    return $null
}

function Get-ProjectVersion {
    $tomlPath = Join-Path $RootDir 'pyproject.toml'
    $content = Get-Content $tomlPath -Raw
    if ($content -match 'version\s*=\s*"([^"]+)"') {
        return $Matches[1]
    }
    return '0.0.0'
}

function Invoke-SmokeTest {
    if ($env:BILITERMINAL_SKIP_SMOKE -eq '1') {
        Write-Host "Skipped smoke verification for $AppDir"
        return
    }

    $smokeHome = Join-Path $BuildDir 'smoke-home'
    $smokeLog = Join-Path $smokeHome 'launcher.log'
    $smokeOutput = Join-Path $BuildDir 'smoke-launch.txt'

    if (Test-Path $smokeHome) { Remove-Item $smokeHome -Recurse -Force }
    if (Test-Path $smokeOutput) { Remove-Item $smokeOutput -Force }
    New-Item -ItemType Directory -Path $smokeHome -Force | Out-Null

    $env:BILITERMINAL_HOME = $smokeHome
    $env:BILITERMINAL_LOG_FILE = $smokeLog
    $env:TERM = 'xterm-256color'

    $launchBat = Join-Path $AppDir 'launch.bat'
    & cmd /c "`"$launchBat`" --help" 2>&1 | Out-File -FilePath $smokeOutput -Encoding utf8

    $output = Get-Content $smokeOutput -Raw
    if ($output -notmatch 'usage:') {
        Write-Error "Smoke verification did not reach bundled runtime help output`n$output"
    }
    $logContent = if (Test-Path $smokeLog) { Get-Content $smokeLog -Raw } else { '' }
    if ($logContent -notmatch 'exited with status: 0') {
        Write-Error "Bundled runtime success marker missing from smoke log`n$logContent"
    }
    if ($logContent -match 'python fallback') {
        Write-Error "Smoke verification unexpectedly used python fallback`n$logContent"
    }

    Write-Host "Smoke-verified $AppDir"
}

# --- Clean previous builds ---
if (Test-Path $AppDir) { Remove-Item $AppDir -Recurse -Force }
if (Test-Path $ZipPath) { Remove-Item $ZipPath -Force }
if (Test-Path $BuildDir) { Remove-Item $BuildDir -Recurse -Force }
New-Item -ItemType Directory -Path $DistDir -Force | Out-Null
New-Item -ItemType Directory -Path $BuildDir -Force | Out-Null

# --- Resolve tools ---
$pyinstallerBin = if ($env:BILITERMINAL_PYINSTALLER) { $env:BILITERMINAL_PYINSTALLER }
                   elseif (Get-Command pyinstaller -ErrorAction SilentlyContinue) { (Get-Command pyinstaller).Source }
                   else { $null }

if (-not $pyinstallerBin) {
    # Try via python -m PyInstaller
    $pyinstallerBin = $null
    $testResult = & python -m PyInstaller --version 2>&1
    if ($LASTEXITCODE -eq 0) {
        $pyinstallerBin = 'python'
        $pyinstallerMode = '-m'
    }
}

if (-not $pyinstallerBin) {
    Write-Error "pyinstaller is required to build a standalone Windows distribution`nhint: python -m pip install -e `".[build]`""
}

$pythonBuildBin = if ($env:BILITERMINAL_BUILD_PYTHON) { $env:BILITERMINAL_BUILD_PYTHON }
                  else { Resolve-Command @('python', 'python3') }

if (-not $pythonBuildBin) {
    Write-Error 'python is required to finalize the Windows distribution'
}

# --- PyInstaller bundle ---
$runtimeEntry = Join-Path $WindowsDir 'runtime_entry.py'

if ($pyinstallerMode -eq '-m') {
    & python -m PyInstaller `
        --noconfirm `
        --clean `
        --onedir `
        --console `
        --name $AppName `
        --distpath $RuntimeStageDir `
        --workpath $RuntimeWorkDir `
        --specpath $RuntimeSpecDir `
        --paths $RootDir `
        --collect-data bili_terminal `
        $runtimeEntry
} else {
    & $pyinstallerBin `
        --noconfirm `
        --clean `
        --onedir `
        --console `
        --name $AppName `
        --distpath $RuntimeStageDir `
        --workpath $RuntimeWorkDir `
        --specpath $RuntimeSpecDir `
        --paths $RootDir `
        --collect-data bili_terminal `
        $runtimeEntry
}

if ($LASTEXITCODE -ne 0) {
    Write-Error "PyInstaller failed with exit code $LASTEXITCODE"
}

$runtimeExe = Join-Path $RuntimeSourceDir "$AppName.exe"
if (-not (Test-Path $runtimeExe)) {
    Write-Error "Bundled runtime was not produced at $RuntimeSourceDir\$AppName.exe"
}

# --- Create distribution directory structure ---
New-Item -ItemType Directory -Path $AppDir -Force | Out-Null
New-Item -ItemType Directory -Path $PayloadDir -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $PayloadDir 'tui') -Force | Out-Null
New-Item -ItemType Directory -Path $RuntimeDir -Force | Out-Null

# --- Copy launcher ---
Copy-Item (Join-Path $WindowsDir 'launch.bat') (Join-Path $AppDir 'launch.bat')

# --- Copy source payload ---
Copy-Item (Join-Path $RootDir 'bili_terminal\__init__.py') (Join-Path $PayloadDir '__init__.py')
Copy-Item (Join-Path $RootDir 'bili_terminal\__main__.py') (Join-Path $PayloadDir '__main__.py')
Copy-Item (Join-Path $RootDir 'bili_terminal\bilibili_cli.py') (Join-Path $PayloadDir 'bilibili_cli.py')
Copy-Item (Join-Path $RootDir 'bili_terminal\platform_audio.py') (Join-Path $PayloadDir 'platform_audio.py')
Copy-Item (Join-Path $RootDir 'bili_terminal\platform_audio_nt.py') (Join-Path $PayloadDir 'platform_audio_nt.py')
Copy-Item (Join-Path $RootDir 'bili_terminal\platform_audio_posix.py') (Join-Path $PayloadDir 'platform_audio_posix.py')
Copy-Tree (Join-Path $RootDir 'bili_terminal\tui') (Join-Path $PayloadDir 'tui')

# --- Copy PyInstaller runtime ---
Copy-Tree $RuntimeSourceDir $RuntimeDir

# --- Write version metadata ---
$version = Get-ProjectVersion
Set-Content -Path (Join-Path $AppDir 'version.txt') -Value $version -Encoding utf8NoBOM

# --- Clean __pycache__ ---
Get-ChildItem -Path $AppDir -Directory -Recurse -Filter '__pycache__' | Remove-Item -Recurse -Force
Get-ChildItem -Path $AppDir -File -Recurse -Filter '*.pyc' | Remove-Item -Force

# --- Smoke test ---
Invoke-SmokeTest

# --- Create zip ---
if (Test-Path $ZipPath) { Remove-Item $ZipPath -Force }
Compress-Archive -Path $AppDir -DestinationPath $ZipPath -Force

Write-Host "Built $AppDir"
Write-Host "Packed $ZipPath"
```

- [ ] **Step 2: Commit**

```bash
git add build_windows_app.ps1
git commit -m "feat: add Windows PowerShell build script for standalone distribution"
```

---

### Task 4: Install PyInstaller and run a test build

**Files:** None (verification only)

- [ ] **Step 1: Install PyInstaller build dependency**

Run: `python -m pip install -e ".[build]"`
Expected: Successfully installs pyinstaller

- [ ] **Step 2: Run the build**

Run: `powershell -ExecutionPolicy Bypass -File build_windows_app.ps1`
Expected: `Built <path>\dist\BiliTerminal` and `Packed <path>\dist\BiliTerminal-Windows.zip`

- [ ] **Step 3: Verify the distribution structure**

Run:
```powershell
ls dist\BiliTerminal\
ls dist\BiliTerminal\runtime\BiliTerminal\BiliTerminal.exe
type dist\BiliTerminal\version.txt
```
Expected: `launch.bat`, `app/`, `runtime/`, `version.txt` all present; `BiliTerminal.exe` exists; `version.txt` reads `0.3.0`

- [ ] **Step 4: Commit (no changes, verification only)**
