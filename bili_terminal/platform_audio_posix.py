from __future__ import annotations

import os
import signal


def pid_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def send_signal(pid: int, sig: int) -> None:
    os.kill(pid, sig)


def pause_process(pid: int) -> None:
    os.kill(pid, signal.SIGSTOP)


def resume_process(pid: int) -> None:
    os.kill(pid, signal.SIGCONT)


def terminate_process(pid: int) -> None:
    os.kill(pid, signal.SIGTERM)


def kill_process(pid: int) -> None:
    os.kill(pid, signal.SIGKILL)


def suspend_signal() -> int:
    return signal.SIGSTOP


def resume_signal() -> int:
    return signal.SIGCONT


def has_pause_resume() -> bool:
    return True
