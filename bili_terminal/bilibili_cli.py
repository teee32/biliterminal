#!/usr/bin/env python3
"""Backward-compatible facade for the split bili_terminal modules.

历史上整个客户端都在这个文件里，外部脚本可能仍然 `from bili_terminal import
bilibili_cli`。真正的实现已经拆分到 models/client/history/audio/output/repl/
tui/cli 等模块，这里只做重导出。
"""

from __future__ import annotations

import signal
import subprocess
import urllib.error
import urllib.parse
import urllib.request

if __package__ in (None, ""):
    # 支持 README 里的 `python3 bili_terminal/bilibili_cli.py ...` 直接执行方式
    import os as _os
    import sys as _sys

    _sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
    __package__ = "bili_terminal"

from .audio import (
    MACOS_AUDIO_HELPER_NAME,
    audio_action_for_item,
    audio_control_target,
    audio_playback_state_path,
    audio_worker_log_path,
    build_audio_player_command,
    build_ffplay_command,
    build_mpv_command,
    cleanup_audio_ipc_socket,
    cleanup_audio_media_path,
    clear_audio_playback_state,
    compile_macos_audio_helper,
    download_audio_to_path,
    executable_file_exists,
    load_audio_playback_state,
    macos_audio_helper_binary_path,
    macos_audio_helper_path,
    macos_audio_helper_source_path,
    macos_cached_audio_helper_path,
    mpv_ipc_socket_path,
    pause_audio_playback,
    pause_signal_for_state,
    pid_exists,
    play_audio_for_item,
    play_audio_stream,
    prepare_audio_temp_path,
    resume_audio_playback,
    resume_signal_for_state,
    run_audio_worker,
    save_audio_playback_state,
    send_audio_signal,
    send_mpv_ipc_command,
    set_mpv_paused,
    spawn_audio_worker,
    stop_audio_playback,
    stream_mime_type,
    toggle_audio_playback,
    wait_for_audio_exit,
)
from .cli import build_parser, main, run_once
from .client import (
    COMMENT_WBI_MIXIN_TABLE,
    COMMENT_WEB_LOCATION,
    DEFAULT_TIMEOUT,
    DEFAULT_USER_AGENT,
    BilibiliClient,
    decode_response_body,
    extract_audio_stream,
    mixin_wbi_key,
    sign_wbi_params,
)
from .history import MAX_FAVORITE_ITEMS, MAX_HISTORY_ITEMS, HistoryStore
from .models import (
    AID_PATTERN,
    BVID_PATTERN,
    AudioPlaybackState,
    AudioStream,
    BilibiliAPIError,
    CommentItem,
    ListState,
    VideoItem,
    build_video_url,
    build_watch_url,
    comments_from_payload,
    comments_from_thread_payload,
    item_from_payload,
    item_to_history_payload,
    parse_video_ref,
    video_key_from_item,
    video_key_from_payload,
    video_key_from_ref,
)
from .output import (
    build_detail_lines,
    print_comments,
    print_favorites,
    print_history,
    print_video_detail,
    print_video_list,
)
from .paths import DEFAULT_HISTORY_FILENAME, DEFAULT_STATE_DIR, default_history_path, default_state_dir
from .repl import BilibiliCLI, open_video_target
from .textutil import (
    centered_x,
    char_width,
    compact_whitespace,
    display_width,
    format_timestamp,
    has_cjk,
    human_count,
    is_suspicious_keyword,
    normalize_duration,
    normalize_keyword,
    repair_mojibake,
    shorten,
    strip_html,
    truncate_display,
    wrap_display,
)
from .tui import BILIBILI_PINK_RGB, HOME_CHANNELS, BilibiliTUI, run_tui

__all__ = [name for name in dir() if not name.startswith("_")]

if __name__ == "__main__":
    raise SystemExit(main())
