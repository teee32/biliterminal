from __future__ import annotations

import os

# 历史上默认状态目录是相对当前工作目录的 ".omx/state"，会导致登录态/凭证
# 散落在各个运行目录、且 cd 后“登录消失”。仅作为已有安装的回退保留。
LEGACY_STATE_DIR = ".omx/state"
DEFAULT_STATE_DIR = LEGACY_STATE_DIR  # 兼容旧引用方（如 bilibili_cli 的重导出）
DEFAULT_HISTORY_FILENAME = "bilibili-cli-history.json"


def _home_anchored_state_dir() -> str:
    """与 macOS 启动器 (BILITERMINAL_HOME=~/.biliterminal) 保持一致、且兼容 XDG。"""
    xdg_state = os.environ.get("XDG_STATE_HOME", "").strip()
    if xdg_state:
        return os.path.join(os.path.expanduser(xdg_state), "biliterminal")
    return os.path.join(os.path.expanduser("~"), ".biliterminal", "state")


def default_state_dir() -> str:
    state_dir = os.environ.get("BILITERMINAL_STATE_DIR", "").strip()
    if state_dir:
        return os.path.expanduser(state_dir)
    home_dir = os.environ.get("BILITERMINAL_HOME", "").strip()
    if home_dir:
        return os.path.join(os.path.expanduser(home_dir), "state")
    # 若旧的 CWD 相对目录已存在数据，沿用它以免老用户登录态丢失；
    # 否则使用 home 锚定目录，避免把凭证写进当前工作目录。
    if os.path.isdir(LEGACY_STATE_DIR):
        return LEGACY_STATE_DIR
    return _home_anchored_state_dir()


def default_history_path() -> str:
    return os.path.join(default_state_dir(), DEFAULT_HISTORY_FILENAME)
