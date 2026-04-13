from __future__ import annotations

import os as _os

if _os.name == "nt":
    from .platform_audio_nt import (
        kill_process,
        has_pause_resume,
        pause_process,
        pid_exists,
        resume_process,
        send_signal,
        suspend_signal,
        resume_signal,
        terminate_process,
    )
else:
    from .platform_audio_posix import (
        kill_process,
        has_pause_resume,
        pause_process,
        pid_exists,
        resume_process,
        send_signal,
        suspend_signal,
        resume_signal,
        terminate_process,
    )

__all__ = [
    "kill_process",
    "has_pause_resume",
    "pause_process",
    "pid_exists",
    "resume_process",
    "send_signal",
    "suspend_signal",
    "resume_signal",
    "terminate_process",
]
