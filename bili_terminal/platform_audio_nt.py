from __future__ import annotations

import ctypes
import os
import signal


_kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
_ntdll = ctypes.windll.ntdll  # type: ignore[attr-defined]

_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_PROCESS_SUSPEND_RESUME = 0x0800
_PROCESS_TERMINATE = 0x0001
_STILL_ACTIVE = 259


def pid_exists(pid: int) -> bool:
    handle = _kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        err = _kernel32.GetLastError()
        if err == 87:
            return False
        if err == 5:
            return True
        return False
    try:
        exit_code = ctypes.c_ulong()
        if not _kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return True
        return exit_code.value == _STILL_ACTIVE
    finally:
        _kernel32.CloseHandle(handle)


def send_signal(pid: int, sig: int) -> None:
    if not pid_exists(pid):
        raise ProcessLookupError(f"Process {pid} does not exist")
    if sig in (signal.CTRL_C_EVENT, signal.CTRL_BREAK_EVENT):
        os.kill(pid, sig)
        return
    terminate_process(pid)


def pause_process(pid: int) -> None:
    handle = _kernel32.OpenProcess(_PROCESS_SUSPEND_RESUME, False, pid)
    if not handle:
        err = _kernel32.GetLastError()
        if err == 87:
            raise ProcessLookupError(f"Process {pid} does not exist")
        if err == 5:
            raise PermissionError(f"Access denied suspending process {pid}")
        raise OSError(f"Cannot open process {pid} for suspend (error {err})")
    try:
        status = _ntdll.NtSuspendProcess(handle)
        if status != 0:
            raise OSError(f"NtSuspendProcess failed for pid {pid} (status {status:#x})")
    finally:
        _kernel32.CloseHandle(handle)


def resume_process(pid: int) -> None:
    handle = _kernel32.OpenProcess(_PROCESS_SUSPEND_RESUME, False, pid)
    if not handle:
        err = _kernel32.GetLastError()
        if err == 87:
            raise ProcessLookupError(f"Process {pid} does not exist")
        if err == 5:
            raise PermissionError(f"Access denied resuming process {pid}")
        raise OSError(f"Cannot open process {pid} for resume (error {err})")
    try:
        status = _ntdll.NtResumeProcess(handle)
        if status != 0:
            raise OSError(f"NtResumeProcess failed for pid {pid} (status {status:#x})")
    finally:
        _kernel32.CloseHandle(handle)


def terminate_process(pid: int) -> None:
    handle = _kernel32.OpenProcess(_PROCESS_TERMINATE, False, pid)
    if not handle:
        err = _kernel32.GetLastError()
        if err == 87:
            raise ProcessLookupError(f"Process {pid} does not exist")
        if err == 5:
            raise PermissionError(f"Access denied terminating process {pid}")
        raise OSError(f"Cannot open process {pid} for termination (error {err})")
    try:
        if not _kernel32.TerminateProcess(handle, 1):
            raise OSError(
                f"TerminateProcess failed for pid {pid} (error {_kernel32.GetLastError()})"
            )
    finally:
        _kernel32.CloseHandle(handle)


def kill_process(pid: int) -> None:
    terminate_process(pid)


def suspend_signal() -> int:
    return 0


def resume_signal() -> int:
    return 0


def has_pause_resume() -> bool:
    return True
