# Windows Build Design

## Goal

Create a PowerShell build script (`build_windows_app.ps1`) that produces a self-contained Windows distribution of BiliTerminal, mirroring the structure and logic of `build_macos_app.sh`.

## Product Structure

```
dist/
├── BiliTerminal/                    # Single-directory distribution
│   ├── launch.bat                   # Launcher (mirrors macos/launch.command)
│   ├── version.txt                  # Version metadata (mirrors Info.plist)
│   ├── app/
│   │   └── bili_terminal/           # Source payload (same as macOS)
│   │       ├── __init__.py
│   │       ├── __main__.py
│   │       ├── bilibili_cli.py
│   │       ├── platform_audio.py
│   │       ├── platform_audio_nt.py
│   │       ├── platform_audio_posix.py
│   │       └── tui/
│   └── runtime/
│       └── BiliTerminal/            # PyInstaller onedir output
│           ├── BiliTerminal.exe
│           └── ...
└── BiliTerminal-Windows.zip         # Final archive
```

## Build Pipeline

| Step | macOS | Windows |
|------|-------|---------|
| 1. PyInstaller bundle | `--onedir --console` → runtime/ | Same |
| 2. App skeleton | `osacompile` → .app | Create directory tree |
| 3. Copy launcher | `launch.command` | `launch.bat` |
| 4. Copy source payload | `app/bili_terminal/` | Same |
| 5. Compile native audio helper | clang → exe | Skip (ffplay) |
| 6. Metadata | `Info.plist` version | `version.txt` |
| 7. Code signing | `codesign` | Skip |
| 8. Smoke test | `--help` output check | Same |
| 9. Archive | `ditto` → zip | `Compress-Archive` → zip |

## New Files

- `build_windows_app.ps1` — Build script
- `bili_terminal/windows/launch.bat` — Launcher template
- `bili_terminal/windows/runtime_entry.py` — Reuses macOS runtime_entry.py logic

## launch.bat Logic

1. Set environment variables (`BILITERMINAL_HOME`, `TERM=xterm-256color`, `COLORTERM=truecolor`)
2. Prefer bundled runtime: `runtime\BiliTerminal\BiliTerminal.exe`
3. Fallback to system `python -m bili_terminal --tui`
4. Log to `launcher.log`

## Smoke Test

Run `launch.bat --help`, verify output contains `usage: BiliTerminal`.

## Differences from macOS Build

- No osacompile / .app bundle / codesign / ditto
- No native audio helper compilation (Windows uses ffplay via platform_audio_nt.py)
- Uses `Compress-Archive` instead of ditto
- Launcher is `.bat` instead of `.command`
- Version metadata in `version.txt` instead of `Info.plist`
