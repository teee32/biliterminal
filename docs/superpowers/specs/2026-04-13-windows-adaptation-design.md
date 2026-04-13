# Windows 11 Terminal Adaptation Design

## Goal

Make all BiliTerminal features work on Windows 11 Terminal while preserving macOS compatibility and minimizing merge conflicts with upstream.

## Incompatible Code Paths

| # | Issue | Location | Fix |
|---|-------|----------|-----|
| 1 | `SIGSTOP`/`SIGCONT`/`SIGTERM`/`SIGKILL`/`SIGUSR1`/`SIGUSR2` absent on Windows | `bilibili_cli.py:816,820,836,842,848` | Platform audio layer |
| 2 | `os.kill(pid, 0)` for pid check behaves differently on Windows | `bilibili_cli.py:720-727` | Platform audio layer |
| 3 | `pause_audio_playback`/`resume_audio_playback` raise on `os.name == "nt"` | `bilibili_cli.py:860,882` | Platform audio layer |
| 4 | `send_audio_signal` uses `os.kill` with POSIX signals | `bilibili_cli.py:803-804` | Platform audio layer |
| 5 | Bash launch scripts unusable on Windows | `biliterminal`, `bili_terminal/start.sh` | New `.bat` file |
| 6 | `executable_file_exists` uses `os.X_OK` (no-op on Windows) | `bilibili_cli.py:657-658` | Platform guard in posix module only |

## Architecture: Platform Audio Layer

### New Files

```
bili_terminal/
  platform_audio.py          # Public API dispatcher (import-based branching)
  platform_audio_posix.py    # POSIX implementation (extracted from bilibili_cli.py)
  platform_audio_nt.py       # Windows implementation (ctypes NtSuspendProcess)
biliterminal.bat             # Windows launch script
```

### Public API (`platform_audio.py`)

Exposes these functions that `bilibili_cli.py` will import:

- `pid_exists(pid: int) -> bool`
- `send_signal(pid: int, sig: int) -> None`
- `pause_process(pid: int) -> None`
- `resume_process(pid: int) -> None`
- `terminate_process(pid: int) -> None`
- `kill_process(pid: int) -> None`
- `suspend_signal() -> int`  (POSIX: SIGSTOP; Windows: N/A — uses pause_process)
- `resume_signal() -> int`   (POSIX: SIGCONT; Windows: N/A — uses resume_process)
- `has_pause_resume() -> bool`  (POSIX: True; Windows: True via NtSuspendProcess)

### Windows Implementation (`platform_audio_nt.py`)

- **pid_exists**: `ctypes` `OpenProcess` + `GetExitCodeProcess` (matches psutil behavior)
- **pause**: `ctypes` `NtSuspendProcess` via ntdll.dll (zero-dependency, same effect as SIGSTOP)
- **resume**: `ctypes` `NtResumeProcess` via ntdll.dll (same effect as SIGCONT)
- **terminate**: `ctypes` `TerminateProcess` (equivalent to SIGKILL for stop_audio_playback fallback)
- **send_signal**: `os.kill(pid, sig)` — only `signal.CTRL_C_EVENT` / `signal.CTRL_BREAK_EVENT` are valid on Windows; terminate uses `TerminateProcess` instead
- **kill_process**: Same as terminate on Windows

### POSIX Implementation (`platform_audio_posix.py`)

- Exact copy of current logic from `bilibili_cli.py`, zero behavioral change
- `pid_exists` — `os.kill(pid, 0)` with `ProcessLookupError`/`PermissionError` handling
- `send_signal` — `os.kill(pid, sig)`
- `pause_process` — `os.kill(pid, signal.SIGSTOP)`
- `resume_process` — `os.kill(pid, signal.SIGCONT)`
- `terminate_process` — `os.kill(pid, signal.SIGTERM)`
- `kill_process` — `os.kill(pid, signal.SIGKILL)`
- `suspend_signal` / `resume_signal` — returns `signal.SIGSTOP` / `signal.SIGCONT`
  (macOS-native helper path is handled in `bilibili_cli.py` as before — only the default POSIX fallback changes)

### Changes to `bilibili_cli.py`

1. Add `from . import platform_audio` near other imports
2. Replace `pid_exists()` body with `return platform_audio.pid_exists(pid)`
3. Replace `send_audio_signal()` body with `platform_audio.send_signal(pid, sig)`
4. In `stop_audio_playback()`: replace `signal.SIGTERM` calls with `platform_audio.terminate_process()`, replace `signal.SIGKILL` call with `platform_audio.kill_process()`
5. In `pause_signal_for_state()` / `resume_signal_for_state()`: add `hasattr(signal, "SIGUSR1")`/`"SIGUSR2"` guards for macOS-native code paths (these signals don't exist on Windows); default returns now use `platform_audio.suspend_signal()` / `platform_audio.resume_signal()`
6. In `pause_audio_playback()` / `resume_audio_playback()`: remove `os.name == "nt"` raise; use `platform_audio.pause_process()` / `platform_audio.resume_process()` for non-macos-native backends
7. Keep `import signal` (still needed for `SIGUSR1`/`SIGUSR2`/`SIGTERM`/`SIGKILL`/`SIGSTOP`/`SIGCONT` on POSIX)

### biliterminal.bat

- Sets `PYTHONPATH` and `TERM=xterm-256color`
- Defaults to `--tui` (Textual) since no Windows Terminal issue with Textual
- Passes all CLI args through

## What Does NOT Change

- macOS `.app` bundle, `build_macos_app.sh`, `BiliTerminal.applescript`
- macOS audio helper (ObjC) and `afplay` path
- User-Agent string, API endpoints, WBI signing
- Textual UI (screens, widgets, CSS) — already works on Windows
- Legacy curses TUI — intentionally not adapted for Windows
- `pyproject.toml` — no new dependencies (ctypes is stdlib)

## Merge Conflict Analysis

- **New files** (`platform_audio*.py`, `.bat`): zero conflict (upstream doesn't have them)
- **bilibili_cli.py**: changes are import additions and function body replacements — if upstream changes function bodies, the diff will show "replace entire body" which is easy to re-apply
- Upstream adding new audio functions: they'd go into `bilibili_cli.py` as before; developer just adds `platform_audio.*` delegation

## Testing

- `test_platform_audio.py` — unit tests for both posix and nt modules (mock ctypes on non-Windows)
- Existing audio tests continue to work (they mock `pid_exists`/`send_audio_signal` which now delegate to platform_audio)