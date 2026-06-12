from __future__ import annotations

import os

DEFAULT_STATE_DIR = ".omx/state"
DEFAULT_HISTORY_FILENAME = "bilibili-cli-history.json"


def default_state_dir() -> str:
    state_dir = os.environ.get("BILITERMINAL_STATE_DIR", "").strip()
    if state_dir:
        return os.path.expanduser(state_dir)
    home_dir = os.environ.get("BILITERMINAL_HOME", "").strip()
    if home_dir:
        return os.path.join(os.path.expanduser(home_dir), "state")
    return DEFAULT_STATE_DIR


def default_history_path() -> str:
    return os.path.join(default_state_dir(), DEFAULT_HISTORY_FILENAME)
