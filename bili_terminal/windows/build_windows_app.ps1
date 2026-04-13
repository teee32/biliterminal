#Requires -Version 5.1
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

$RootDir = Resolve-Path (Join-Path $PSScriptRoot '..\..')
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
    $smokeOutput = Join-Path $BuildDir 'smoke-launch.txt'

    if (Test-Path $smokeHome) { Remove-Item $smokeHome -Recurse -Force }
    if (Test-Path $smokeOutput) { Remove-Item $smokeOutput -Force }
    New-Item -ItemType Directory -Path $smokeHome -Force | Out-Null

    $env:BILITERMINAL_HOME = $smokeHome
    $env:TERM = 'xterm-256color'

    $runtimeExe = Join-Path $RuntimeDir 'BiliTerminal.exe'
    & $runtimeExe --help 2>&1 | Out-File -FilePath $smokeOutput -Encoding utf8

    $output = Get-Content $smokeOutput -Raw
    if ($output -notmatch 'usage:') {
        Write-Error "Smoke verification did not reach bundled runtime help output`n$output"
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
$pyinstallerBin = $null
$pyinstallerMode = 'direct'

if ($env:BILITERMINAL_PYINSTALLER) {
    $pyinstallerBin = $env:BILITERMINAL_PYINSTALLER
} elseif (Get-Command pyinstaller -ErrorAction SilentlyContinue) {
    $pyinstallerBin = (Get-Command pyinstaller).Source
}

if (-not $pyinstallerBin) {
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
$versionPath = Join-Path $AppDir 'version.txt'
[System.IO.File]::WriteAllText($versionPath, $version, (New-Object System.Text.UTF8Encoding $false))

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