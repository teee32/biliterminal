#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import gzip
import hashlib
import http.cookiejar
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import zlib
from dataclasses import dataclass
from typing import Any


DEFAULT_TIMEOUT = 15
DEFAULT_STATE_DIR = ".biliterminal/state"
DEFAULT_HISTORY_FILENAME = "biliterminal-history.json"
MAX_HISTORY_ITEMS = 40
MAX_FAVORITE_ITEMS = 200
MAX_WATCH_LATER_ITEMS = 200
MACOS_AUDIO_HELPER_NAME = "biliterminal-audio-helper"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
)

HOME_CHANNELS: list[dict[str, Any]] = [
    {"label": "首页", "source": "recommend"},
    {"label": "热门", "source": "popular"},
    {"label": "入站必刷", "source": "precious"},
    {"label": "动画", "source": "region", "rid": 1},
    {"label": "游戏", "source": "region", "rid": 4},
    {"label": "知识", "source": "region", "rid": 36},
    {"label": "影视", "source": "region", "rid": 181},
    {"label": "科技", "source": "region", "rid": 188},
    {"label": "音乐", "source": "region", "rid": 3},
    {"label": "番剧", "source": "bangumi", "category": "番剧"},
]

RANK_REGION_ALIASES: dict[str, tuple[int, str]] = {
    "动画": (1, "动画"),
    "anime": (1, "动画"),
    "音乐": (3, "音乐"),
    "music": (3, "音乐"),
    "游戏": (4, "游戏"),
    "game": (4, "游戏"),
    "games": (4, "游戏"),
    "知识": (36, "知识"),
    "knowledge": (36, "知识"),
    "影视": (181, "影视"),
    "movie": (181, "影视"),
    "tv": (181, "影视"),
    "科技": (188, "科技"),
    "tech": (188, "科技"),
}

BANGUMI_CATEGORY_META: dict[str, dict[str, Any]] = {
    "番剧": {"label": "番剧", "season_type": 1},
    "影视": {"label": "影视", "season_type": 2},
    "国创": {"label": "国创", "season_type": 4},
}

BANGUMI_CATEGORY_ALIASES: dict[str, str] = {
    "anime": "番剧",
    "bangumi": "番剧",
    "番剧": "番剧",
    "movie": "影视",
    "tv": "影视",
    "影视": "影视",
    "guochuang": "国创",
    "国创": "国创",
}

BVID_PATTERN = re.compile(r"(BV[0-9A-Za-z]{10})")
AID_PATTERN = re.compile(r"\bav(\d+)\b", re.IGNORECASE)
HTML_TAG_PATTERN = re.compile(r"<[^>]+>")
WHITESPACE_PATTERN = re.compile(r"\s+")
COMMON_MOJIBAKE_CHARS = set("ÃÂÐÑãäåæçèéêëìíîïðñòóôõöùúûüýþÿ")
INITIAL_STATE_PATTERN = re.compile(r"window\.__INITIAL_STATE__=(\{.*?\});\(function", re.S)
INITIAL_STATE_FALLBACK_PATTERN = re.compile(r"window\.__INITIAL_STATE__=(\{.*?\})\s*var\s+isBilibili", re.S)
COMMENT_WBI_KEYS_PATTERN = re.compile(r'encWbiKeys:\{wbiImgKey:"([^"]+)",wbiSubKey:"([^"]+)"\}')
PLAYINFO_PATTERN = re.compile(r"window\.__playinfo__\s*=\s*(\{.*?\})\s*</script>", re.S)
WBI_KEY_SANITIZE_PATTERN = re.compile(r"[!'()*]")
COMMENT_WEB_LOCATION = 1315875
COMMENT_WBI_MIXIN_TABLE = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35,
    27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13,
    37, 48, 7, 16, 24, 55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4,
    22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36, 20, 34, 44, 52,
]


class BilibiliAPIError(RuntimeError):
    pass


@dataclass(slots=True)
class VideoItem:
    title: str
    author: str
    bvid: str | None
    aid: int | None
    duration: str
    play: int
    danmaku: int
    like: int
    favorite: int
    pubdate: int | None
    description: str
    url: str
    raw: dict[str, Any]


@dataclass(slots=True)
class CommentItem:
    author: str
    message: str
    like: int
    ctime: int | None


@dataclass(slots=True)
class AudioStream:
    title: str
    url: str
    referer: str
    user_agent: str
    source_kind: str


@dataclass(slots=True)
class AudioPlaybackState:
    pid: int | None
    title: str
    video_key: str | None
    backend: str = "process"
    paused: bool = False
    control_pid: int | None = None
    media_path: str | None = None


def strip_html(value: str) -> str:
    return HTML_TAG_PATTERN.sub("", value or "").strip()


def compact_whitespace(value: str) -> str:
    return WHITESPACE_PATTERN.sub(" ", value or "").strip()


def has_cjk(value: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in value)


def repair_mojibake(value: str) -> str:
    cleaned = compact_whitespace(value)
    if not cleaned or has_cjk(cleaned):
        return cleaned
    if any(ord(char) > 255 for char in cleaned):
        return cleaned
    try:
        repaired = cleaned.encode("latin1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return cleaned
    repaired = compact_whitespace(repaired)
    if repaired and repaired != cleaned:
        return repaired
    return cleaned


def is_suspicious_keyword(value: str) -> bool:
    if not value:
        return True
    if "\ufffd" in value:
        return True
    if has_cjk(value):
        return False
    latin1_count = sum(1 for char in value if char in COMMON_MOJIBAKE_CHARS)
    ascii_word_count = sum(1 for char in value if char.isascii() and char.isalnum())
    if len(value) <= 2 and latin1_count == len(value):
        return True
    return latin1_count >= 2 and ascii_word_count <= 2


def normalize_keyword(value: str) -> str:
    cleaned = repair_mojibake(value)
    return "" if is_suspicious_keyword(cleaned) else cleaned


def decode_response_body(raw: bytes, content_encoding: str | None) -> str:
    encoding = (content_encoding or "").lower()
    try:
        if encoding == "gzip":
            raw = gzip.decompress(raw)
        elif encoding == "deflate":
            raw = zlib.decompress(raw)
    except OSError:
        pass
    return raw.decode("utf-8", "replace")


def mixin_wbi_key(img_key: str, sub_key: str) -> str:
    merged = img_key + sub_key
    return "".join(merged[index] for index in COMMENT_WBI_MIXIN_TABLE if index < len(merged))[:32]


def sign_wbi_params(params: dict[str, Any], img_key: str, sub_key: str) -> dict[str, Any]:
    signed = dict(params)
    signed["wts"] = str(round(time.time()))
    for key, value in list(signed.items()):
        if isinstance(value, str):
            signed[key] = WBI_KEY_SANITIZE_PATTERN.sub("", value)
    query = "&".join(
        f"{urllib.parse.quote(str(key), safe='')}={urllib.parse.quote(str(signed[key]), safe='')}"
        for key in sorted(signed)
    )
    signed["w_rid"] = hashlib.md5(f"{query}{mixin_wbi_key(img_key, sub_key)}".encode("utf-8")).hexdigest()
    return signed


def char_width(char: str) -> int:
    if unicodedata.combining(char):
        return 0
    return 2 if unicodedata.east_asian_width(char) in {"W", "F"} else 1


def display_width(value: str) -> int:
    return sum(char_width(char) for char in value)


def truncate_display(value: str, width: int, placeholder: str = "...") -> str:
    cleaned = compact_whitespace(value)
    if width <= 0:
        return ""
    if display_width(cleaned) <= width:
        return cleaned
    placeholder_width = display_width(placeholder)
    if placeholder_width >= width:
        result = ""
        current_width = 0
        for char in placeholder:
            char_len = char_width(char)
            if current_width + char_len > width:
                break
            result += char
            current_width += char_len
        return result

    result = ""
    current_width = 0
    for char in cleaned:
        char_len = char_width(char)
        if current_width + char_len + placeholder_width > width:
            break
        result += char
        current_width += char_len
    return result.rstrip() + placeholder


def wrap_display(value: str, width: int) -> list[str]:
    cleaned = compact_whitespace(value)
    if not cleaned:
        return [""]
    if width <= 1:
        return [cleaned]

    lines: list[str] = []
    current = ""
    current_width = 0
    for char in cleaned:
        char_len = char_width(char)
        if current and current_width + char_len > width:
            lines.append(current.rstrip())
            current = char.lstrip() if char.isspace() else char
            current_width = display_width(current)
            continue
        if not current and char.isspace():
            continue
        current += char
        current_width += char_len
    if current:
        lines.append(current.rstrip())
    return lines or [""]


def centered_x(total_width: int, text: str, min_x: int = 0) -> int:
    return max(min_x, (total_width - display_width(text)) // 2)


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


def shorten(value: str, width: int = 96) -> str:
    return truncate_display(value, width)


def human_count(value: int | None) -> str:
    if value is None:
        return "-"
    if value >= 100_000_000:
        return f"{value / 100_000_000:.1f}亿"
    if value >= 10_000:
        return f"{value / 10_000:.1f}万"
    return str(value)


def parse_count_value(value: Any) -> int:
    if value in (None, ""):
        return 0
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    text = compact_whitespace(str(value)).replace(",", "")
    if not text:
        return 0
    multiplier = 1
    if text.endswith("亿"):
        multiplier = 100_000_000
        text = text[:-1]
    elif text.endswith("万"):
        multiplier = 10_000
        text = text[:-1]
    try:
        return int(float(text) * multiplier)
    except ValueError:
        return 0


def format_timestamp(value: int | None) -> str:
    if not value:
        return "-"
    return dt.datetime.fromtimestamp(value).strftime("%Y-%m-%d %H:%M")


def normalize_duration(value: str | int | None) -> str:
    if value is None:
        return "-"
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.isdigit():
            return normalize_duration(int(stripped))
        if ":" in stripped:
            parts = stripped.split(":")
            if all(part.isdigit() for part in parts):
                numbers = [int(part) for part in parts]
                if len(numbers) == 2:
                    return f"{numbers[0]}:{numbers[1]:02d}"
                if len(numbers) == 3:
                    return f"{numbers[0]}:{numbers[1]:02d}:{numbers[2]:02d}"
        return stripped
    minutes, seconds = divmod(int(value), 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def parse_video_ref(value: str) -> tuple[str, str]:
    value = value.strip()
    bvid_match = BVID_PATTERN.search(value)
    if bvid_match:
        return ("bvid", bvid_match.group(1))
    aid_match = AID_PATTERN.search(value)
    if aid_match:
        return ("aid", aid_match.group(1))
    if value.isdigit():
        return ("aid", value)
    raise ValueError(f"无法识别视频标识: {value}")


def build_video_url(payload: dict[str, Any]) -> str:
    explicit_url = payload.get("url")
    if explicit_url:
        return explicit_url
    redirect_url = payload.get("redirect_url")
    if redirect_url:
        return redirect_url
    link = payload.get("link")
    if link:
        return link
    episode_id = payload.get("episode_id") or payload.get("ep_id")
    if episode_id:
        return f"https://www.bilibili.com/bangumi/play/ep{episode_id}"
    season_id = payload.get("season_id")
    if season_id:
        return f"https://www.bilibili.com/bangumi/play/ss{season_id}"
    media_id = payload.get("media_id")
    if media_id:
        return f"https://www.bilibili.com/bangumi/media/md{media_id}"
    bvid = payload.get("bvid")
    if bvid:
        return f"https://www.bilibili.com/video/{bvid}"
    aid = payload.get("aid")
    if aid:
        return f"https://www.bilibili.com/video/av{aid}"
    return "https://www.bilibili.com/"


def build_watch_url(ref_type: str, value: str) -> str:
    return f"https://www.bilibili.com/video/{value}" if ref_type == "bvid" else f"https://www.bilibili.com/video/av{value}"


def bangumi_episode_id_from_item(item: VideoItem | None) -> int | None:
    if item is None:
        return None
    raw = item.raw or {}
    episode_id = raw.get("episode_id") or raw.get("ep_id")
    if episode_id in (None, ""):
        first_ep = raw.get("first_ep") or {}
        if isinstance(first_ep, dict):
            episode_id = first_ep.get("ep_id") or first_ep.get("episode_id")
    if episode_id not in (None, ""):
        return int(episode_id)
    match = re.search(r"/ep(\d+)", item.url or "")
    if match:
        return int(match.group(1))
    return None


def item_ref_label(item: VideoItem) -> str:
    if item.bvid:
        return item.bvid
    if item.aid is not None:
        return f"av{item.aid}"
    episode_id = bangumi_episode_id_from_item(item)
    if episode_id is not None:
        return f"ep{episode_id}"
    season_id = (item.raw or {}).get("season_id")
    if season_id not in (None, ""):
        return f"ss{season_id}"
    return "-"


def channel_shortcut_index_from_key(key: int, total_channels: int) -> int | None:
    if ord("1") <= key <= ord("9"):
        index = key - ord("1")
        return index if index < total_channels else None
    if key == ord("0") and total_channels >= 10:
        return 9
    return None


def video_lookup_ref_from_item(item: VideoItem | None) -> str | None:
    if item is None:
        return None
    if item.bvid:
        return item.bvid
    if item.aid is not None:
        return str(item.aid)
    return None


def is_bangumi_item(item: VideoItem | None) -> bool:
    if item is None:
        return False
    if "/bangumi/" in (item.url or ""):
        return True
    raw = item.raw or {}
    return any(raw.get(field) not in (None, "") for field in ("episode_id", "ep_id", "season_id", "media_id"))


def resolve_region_rid(region: str | None = None, rid: int | None = None) -> tuple[int, str]:
    if rid is not None:
        label = next((str(channel["label"]) for channel in HOME_CHANNELS if channel.get("rid") == rid), f"分区 {rid}")
        if region and region.strip():
            label = region.strip()
        return rid, label
    if not region or not region.strip():
        raise ValueError("请提供分区名，或用 --rid 指定分区 ID")
    resolved = RANK_REGION_ALIASES.get(region.strip().lower())
    if resolved is None:
        available = "、".join(sorted({label for _, label in RANK_REGION_ALIASES.values()}))
        raise ValueError(f"未知分区: {region}（可用: {available}，或直接传 --rid）")
    return resolved


def resolve_bangumi_category(category: str | None = None) -> dict[str, Any]:
    normalized = (category or "番剧").strip().lower()
    key = BANGUMI_CATEGORY_ALIASES.get(normalized, "番剧")
    return BANGUMI_CATEGORY_META[key]


def build_bangumi_title(category: str, *, index: bool = False, page: int = 1, area: str | None = None) -> str:
    mode = "索引" if index else "更新"
    suffix = f" · {area}" if area else ""
    return f"{category}{mode}{suffix} | 第 {page} 页"


def extract_audio_stream(
    playinfo: dict[str, Any],
    *,
    referer: str,
    user_agent: str,
    title: str,
) -> AudioStream:
    data = playinfo.get("data")
    if not isinstance(data, dict):
        result = playinfo.get("result")
        if isinstance(result, dict):
            data = result
    if not isinstance(data, dict):
        data = playinfo if isinstance(playinfo, dict) else {}
    dash = data.get("dash") or {}
    audio_candidates: list[dict[str, Any]] = []
    for entry in dash.get("audio") or []:
        if isinstance(entry, dict):
            audio_candidates.append(entry)
    flac_audio = (dash.get("flac") or {}).get("audio")
    if isinstance(flac_audio, dict):
        audio_candidates.append(flac_audio)
    for entry in (dash.get("dolby") or {}).get("audio") or []:
        if isinstance(entry, dict):
            audio_candidates.append(entry)

    if audio_candidates:
        selected = max(audio_candidates, key=lambda entry: int(entry.get("bandwidth") or entry.get("id") or 0))
        stream_url = selected.get("baseUrl") or selected.get("base_url")
        if stream_url:
            return AudioStream(
                title=title,
                url=str(stream_url),
                referer=referer,
                user_agent=user_agent,
                source_kind="dash-audio",
            )

    for entry in data.get("durl") or []:
        if not isinstance(entry, dict):
            continue
        stream_url = entry.get("url")
        if stream_url:
            return AudioStream(
                title=title,
                url=str(stream_url),
                referer=referer,
                user_agent=user_agent,
                source_kind="media",
            )

    raise BilibiliAPIError("当前视频没有可用音频流")


def build_audio_player_command(stream: AudioStream) -> list[str] | None:
    if shutil.which("mpv"):
        return [
            "mpv",
            "--no-video",
            "--force-window=no",
            f"--title={stream.title}",
            f"--referrer={stream.referer}",
            f"--user-agent={stream.user_agent}",
            stream.url,
        ]
    if shutil.which("ffplay"):
        return [
            "ffplay",
            "-nodisp",
            "-autoexit",
            "-loglevel",
            "warning",
            "-headers",
            f"Referer: {stream.referer}\r\nUser-Agent: {stream.user_agent}\r\n",
            stream.url,
        ]
    return None


def audio_worker_log_path() -> str:
    return os.path.join(default_state_dir(), "audio-playback.log")


def audio_playback_state_path() -> str:
    return os.path.join(default_state_dir(), "audio-playback.json")


def macos_audio_helper_source_path() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "macos", "biliterminal_audio_helper.m")


def macos_audio_helper_binary_path() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), MACOS_AUDIO_HELPER_NAME)


def macos_cached_audio_helper_path() -> str:
    return os.path.join(default_state_dir(), "bin", MACOS_AUDIO_HELPER_NAME)


def executable_file_exists(path: str) -> bool:
    return os.path.isfile(path) and os.access(path, os.X_OK)


def compile_macos_audio_helper(source_path: str, output_path: str) -> None:
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    command = [
        "clang",
        "-fobjc-arc",
        "-framework",
        "Foundation",
        "-framework",
        "AVFoundation",
        source_path,
        "-o",
        output_path,
    ]
    try:
        subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        raise BilibiliAPIError(exc.stderr.strip() or "macOS 音频 helper 编译失败") from exc
    os.chmod(output_path, 0o755)


def macos_audio_helper_path() -> str | None:
    if sys.platform != "darwin":
        return None

    configured_path = os.environ.get("BILITERMINAL_AUDIO_HELPER", "").strip()
    if configured_path:
        expanded = os.path.expanduser(configured_path)
        if executable_file_exists(expanded):
            return expanded

    bundled_path = macos_audio_helper_binary_path()
    if executable_file_exists(bundled_path):
        return bundled_path

    source_path = macos_audio_helper_source_path()
    cached_path = macos_cached_audio_helper_path()
    if not os.path.isfile(source_path) or shutil.which("clang") is None:
        return None

    needs_rebuild = not executable_file_exists(cached_path)
    if not needs_rebuild:
        try:
            needs_rebuild = os.path.getmtime(source_path) > os.path.getmtime(cached_path)
        except OSError:
            needs_rebuild = True
    if needs_rebuild:
        try:
            compile_macos_audio_helper(source_path, cached_path)
        except BilibiliAPIError:
            if not executable_file_exists(cached_path):
                return None
    return cached_path if executable_file_exists(cached_path) else None


def pid_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def save_audio_playback_state(state: AudioPlaybackState) -> None:
    path = audio_playback_state_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(
            {
                "pid": state.pid,
                "title": state.title,
                "video_key": state.video_key,
                "backend": state.backend,
                "paused": state.paused,
                "control_pid": state.control_pid,
                "media_path": state.media_path,
            },
            handle,
            ensure_ascii=False,
            indent=2,
        )


def clear_audio_playback_state() -> None:
    try:
        os.unlink(audio_playback_state_path())
    except FileNotFoundError:
        return


def cleanup_audio_media_path(media_path: str | None) -> None:
    if not media_path:
        return
    try:
        os.unlink(media_path)
    except FileNotFoundError:
        return
    except OSError:
        return


def load_audio_playback_state() -> AudioPlaybackState | None:
    path = audio_playback_state_path()
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None

    if not isinstance(payload, dict):
        clear_audio_playback_state()
        return None

    try:
        pid_value = payload.get("pid")
        state = AudioPlaybackState(
            pid=int(pid_value) if pid_value not in (None, "") else None,
            title=str(payload.get("title") or "当前音频"),
            video_key=payload.get("video_key"),
            backend=str(payload.get("backend") or "process"),
            paused=bool(payload.get("paused")),
            control_pid=int(payload["control_pid"]) if payload.get("control_pid") not in (None, "") else None,
            media_path=str(payload["media_path"]) if payload.get("media_path") else None,
        )
    except (KeyError, TypeError, ValueError):
        cleanup_audio_media_path(payload.get("media_path"))
        clear_audio_playback_state()
        return None

    if state.pid is None or not pid_exists(state.pid):
        cleanup_audio_media_path(state.media_path)
        clear_audio_playback_state()
        return None
    return state


def send_audio_signal(pid: int, sig: int) -> None:
    os.kill(pid, sig)


def wait_for_audio_exit(pid: int, timeout: float = 1.5) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not pid_exists(pid):
            return
        time.sleep(0.05)


def pause_signal_for_state(state: AudioPlaybackState) -> int:
    return signal.SIGUSR1 if state.backend == "macos-native" else signal.SIGSTOP


def resume_signal_for_state(state: AudioPlaybackState) -> int:
    return signal.SIGUSR2 if state.backend == "macos-native" else signal.SIGCONT


def audio_control_target(state: AudioPlaybackState) -> int | None:
    return state.control_pid or state.pid


def stop_audio_playback(*, silent: bool = False) -> str:
    state = load_audio_playback_state()
    if state is None:
        if silent:
            return ""
        raise BilibiliAPIError("当前没有音频在播放")
    try:
        if state.control_pid and pid_exists(state.control_pid):
            try:
                send_audio_signal(state.control_pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            wait_for_audio_exit(state.control_pid, timeout=0.6)
        if state.pid is not None and pid_exists(state.pid):
            try:
                send_audio_signal(state.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            wait_for_audio_exit(state.pid)
            if pid_exists(state.pid):
                try:
                    send_audio_signal(state.pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass
    except PermissionError:
        pass
    finally:
        cleanup_audio_media_path(state.media_path)
        clear_audio_playback_state()
    return f"已停止音频: {truncate_display(state.title, 40)}"


def pause_audio_playback() -> str:
    if os.name == "nt":
        raise BilibiliAPIError("当前平台不支持暂停音频，请直接停止后重播")
    state = load_audio_playback_state()
    if state is None:
        raise BilibiliAPIError("当前没有音频在播放")
    if state.paused:
        return f"音频已暂停: {truncate_display(state.title, 40)}"
    try:
        target_pid = audio_control_target(state)
        if target_pid is None:
            raise ProcessLookupError
        send_audio_signal(target_pid, pause_signal_for_state(state))
    except ProcessLookupError as exc:
        cleanup_audio_media_path(state.media_path)
        clear_audio_playback_state()
        raise BilibiliAPIError("当前没有音频在播放") from exc
    state.paused = True
    save_audio_playback_state(state)
    return f"已暂停音频: {truncate_display(state.title, 40)}"


def resume_audio_playback() -> str:
    if os.name == "nt":
        raise BilibiliAPIError("当前平台不支持继续音频，请直接重播")
    state = load_audio_playback_state()
    if state is None:
        raise BilibiliAPIError("当前没有音频在播放")
    if not state.paused:
        return f"音频播放中: {truncate_display(state.title, 40)}"
    try:
        target_pid = audio_control_target(state)
        if target_pid is None:
            raise ProcessLookupError
        send_audio_signal(target_pid, resume_signal_for_state(state))
    except ProcessLookupError as exc:
        cleanup_audio_media_path(state.media_path)
        clear_audio_playback_state()
        raise BilibiliAPIError("当前没有音频在播放") from exc
    state.paused = False
    save_audio_playback_state(state)
    return f"已继续播放音频: {truncate_display(state.title, 40)}"


def toggle_audio_playback() -> str:
    state = load_audio_playback_state()
    if state is None:
        raise BilibiliAPIError("当前没有音频在播放")
    if state.paused:
        return resume_audio_playback()
    return pause_audio_playback()


def spawn_audio_worker(stream: AudioStream) -> int:
    log_path = audio_worker_log_path()
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    log_handle = open(log_path, "ab")
    command = audio_worker_command(stream)
    try:
        process = subprocess.Popen(
            command,
            stdout=log_handle,
            stderr=log_handle,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
        return process.pid
    finally:
        log_handle.close()


def audio_worker_command(stream: AudioStream) -> list[str]:
    command = [sys.executable]
    if not getattr(sys, "frozen", False):
        command.append(os.path.abspath(__file__))
    command.extend(
        [
            "audio-worker",
            "--url",
            stream.url,
            "--referer",
            stream.referer,
            "--user-agent",
            stream.user_agent,
            "--title",
            stream.title,
        ]
    )
    return command


def play_audio_stream(stream: AudioStream, *, video_key: str | None = None) -> str:
    command = build_audio_player_command(stream)
    if command is None and macos_audio_helper_path() is None and not (sys.platform == "darwin" and shutil.which("afplay")):
        raise BilibiliAPIError("未找到可用播放器，请安装 mpv 或 ffplay")

    stop_audio_playback(silent=True)
    pid = spawn_audio_worker(stream)
    save_audio_playback_state(
        AudioPlaybackState(
            pid=pid,
            title=stream.title,
            video_key=video_key,
            paused=False,
            control_pid=None,
        )
    )
    if command:
        return f"已开始播放音频: {truncate_display(stream.title, 40)}"
    return f"正在准备音频播放: {truncate_display(stream.title, 40)}"


def prepare_audio_temp_path(url: str) -> str:
    suffix = os.path.splitext(urllib.parse.urlparse(url).path)[1] or ".m4a"
    temp_file = tempfile.NamedTemporaryFile(prefix="biliterminal-audio-", suffix=suffix, delete=False)
    temp_path = temp_file.name
    temp_file.close()
    return temp_path


def download_audio_to_path(url: str, referer: str, user_agent: str, temp_path: str) -> None:
    try:
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": user_agent,
                "Accept": "*/*",
                "Referer": referer,
            },
        )
        with urllib.request.urlopen(request, timeout=60) as response, open(temp_path, "wb") as handle:
            while True:
                chunk = response.read(256 * 1024)
                if not chunk:
                    break
                handle.write(chunk)
    except urllib.error.HTTPError as exc:
        cleanup_audio_media_path(temp_path)
        raise BilibiliAPIError(f"音频下载失败 HTTP {exc.code}: {exc.reason}") from exc
    except urllib.error.URLError as exc:
        cleanup_audio_media_path(temp_path)
        raise BilibiliAPIError(f"音频下载失败: {exc.reason}") from exc


def play_audio_for_item(client: "BilibiliClient", item: VideoItem) -> str:
    stream = client.audio_stream_for_item(item)
    return play_audio_stream(stream, video_key=video_key_from_item(item))


def audio_action_for_item(client: "BilibiliClient", item: VideoItem) -> str:
    state = load_audio_playback_state()
    item_key = video_key_from_item(item)
    if state and state.video_key and item_key == state.video_key:
        return toggle_audio_playback()
    return play_audio_for_item(client, item)


def run_audio_worker(url: str, referer: str, user_agent: str, title: str) -> int:
    stream = AudioStream(title=title or "当前音频", url=url, referer=referer, user_agent=user_agent, source_kind="worker")
    command = build_audio_player_command(stream)
    if command:
        process = subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
        )
        existing_state = load_audio_playback_state()
        save_audio_playback_state(
            AudioPlaybackState(
                pid=os.getpid(),
                title=stream.title,
                video_key=existing_state.video_key if existing_state else None,
                backend="process",
                paused=False,
                control_pid=process.pid,
            )
        )
        return process.wait()

    helper_path = macos_audio_helper_path()
    if helper_path:
        temp_path = prepare_audio_temp_path(url)
        try:
            existing_state = load_audio_playback_state()
            save_audio_playback_state(
                AudioPlaybackState(
                    pid=os.getpid(),
                    title=stream.title,
                    video_key=existing_state.video_key if existing_state else None,
                    backend="macos-native",
                    paused=False,
                    control_pid=None,
                    media_path=temp_path,
                )
            )
            download_audio_to_path(url, referer, user_agent, temp_path)
            process = subprocess.Popen(
                [helper_path, temp_path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
            )
            save_audio_playback_state(
                AudioPlaybackState(
                    pid=os.getpid(),
                    title=stream.title,
                    video_key=existing_state.video_key if existing_state else None,
                    backend="macos-native",
                    paused=False,
                    control_pid=process.pid,
                    media_path=temp_path,
                )
            )
            return process.wait()
        finally:
            cleanup_audio_media_path(temp_path)

    if shutil.which("afplay") is None:
        raise BilibiliAPIError("当前系统没有 afplay，无法执行音频下载兜底播放")

    temp_path = prepare_audio_temp_path(url)
    try:
        existing_state = load_audio_playback_state()
        save_audio_playback_state(
            AudioPlaybackState(
                pid=os.getpid(),
                title=stream.title,
                video_key=existing_state.video_key if existing_state else None,
                backend="afplay",
                paused=False,
                media_path=temp_path,
            )
        )
        download_audio_to_path(url, referer, user_agent, temp_path)
        process = subprocess.Popen(
            ["afplay", temp_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
        )
        save_audio_playback_state(
            AudioPlaybackState(
                pid=os.getpid(),
                title=stream.title,
                video_key=existing_state.video_key if existing_state else None,
                backend="afplay",
                paused=False,
                control_pid=process.pid,
                media_path=temp_path,
            )
        )
        return process.wait()
    finally:
        cleanup_audio_media_path(temp_path)


def item_from_payload(payload: dict[str, Any]) -> VideoItem:
    stat = payload.get("stat") or {}
    owner = payload.get("owner")
    if isinstance(owner, dict):
        author = owner.get("name", "-")
    elif isinstance(owner, str) and owner.strip():
        author = owner.strip()
    else:
        author = payload.get("author") or payload.get("owner_name") or payload.get("up_name") or "-"
    return VideoItem(
        title=strip_html(payload.get("title", "")),
        author=author,
        bvid=payload.get("bvid"),
        aid=payload.get("aid"),
        duration=normalize_duration(payload.get("duration")),
        play=parse_count_value(payload.get("play") or stat.get("view") or 0),
        danmaku=parse_count_value(payload.get("video_review") or payload.get("danmaku") or stat.get("danmaku") or 0),
        like=parse_count_value(payload.get("like") or stat.get("like") or 0),
        favorite=parse_count_value(payload.get("favorites") or stat.get("favorite") or 0),
        pubdate=payload.get("pubdate"),
        description=compact_whitespace(payload.get("description") or payload.get("desc") or ""),
        url=build_video_url(payload),
        raw=payload,
    )


def item_from_bangumi_payload(payload: dict[str, Any], *, category_label: str) -> VideoItem:
    stat = payload.get("stat") or {}
    new_ep = payload.get("new_ep") or {}
    author = compact_whitespace(
        payload.get("subTitle")
        or payload.get("subtitle")
        or payload.get("pub_index")
        or (new_ep.get("index_show") if isinstance(new_ep, dict) else "")
        or category_label
    )
    duration = (
        payload.get("pub_index")
        or payload.get("index_show")
        or payload.get("pub_time")
        or (new_ep.get("index_show") if isinstance(new_ep, dict) else None)
        or payload.get("duration")
        or "-"
    )
    return VideoItem(
        title=strip_html(payload.get("title", "")),
        author=author,
        bvid=payload.get("bvid"),
        aid=payload.get("aid"),
        duration=normalize_duration(duration),
        play=parse_count_value(payload.get("plays") or stat.get("view") or 0),
        danmaku=parse_count_value(payload.get("danmaku") or stat.get("danmaku") or 0),
        like=parse_count_value(payload.get("likes") or stat.get("like") or 0),
        favorite=parse_count_value(payload.get("favorites") or stat.get("favorite") or 0),
        pubdate=payload.get("pub_ts") or payload.get("pubdate"),
        description=compact_whitespace(
            payload.get("evaluate")
            or payload.get("subTitle")
            or payload.get("subtitle")
            or payload.get("delay_reason")
            or ""
        ),
        url=build_video_url(payload),
        raw=payload,
    )


def item_to_history_payload(item: VideoItem) -> dict[str, Any]:
    return {
        "title": item.title,
        "author": item.author,
        "bvid": item.bvid,
        "aid": item.aid,
        "duration": item.duration,
        "play": item.play,
        "danmaku": item.danmaku,
        "like": item.like,
        "favorites": item.favorite,
        "pubdate": item.pubdate,
        "description": item.description,
        "url": item.url,
    }


def video_key_from_payload(payload: dict[str, Any]) -> str | None:
    bvid = payload.get("bvid")
    if bvid:
        return str(bvid)
    aid = payload.get("aid")
    if aid not in (None, ""):
        return f"av{aid}"
    url = payload.get("url")
    return str(url) if url else None


def video_key_from_item(item: VideoItem | None) -> str | None:
    if item is None:
        return None
    return video_key_from_payload(item_to_history_payload(item))


def video_key_from_ref(ref_type: str, value: str) -> str:
    return value if ref_type == "bvid" else f"av{value}"


class HistoryStore:
    def __init__(
        self,
        path: str | None = None,
        max_items: int = MAX_HISTORY_ITEMS,
        max_favorites: int = MAX_FAVORITE_ITEMS,
        max_watch_later: int = MAX_WATCH_LATER_ITEMS,
    ) -> None:
        self.path = path or default_history_path()
        self.max_items = max_items
        self.max_favorites = max_favorites
        self.max_watch_later = max_watch_later
        self._data: dict[str, list[Any]] = {
            "recent_keywords": [],
            "recent_videos": [],
            "favorite_videos": [],
            "watch_later_videos": [],
        }
        self.load()

    def load(self) -> None:
        changed = False
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except FileNotFoundError:
            return
        except (json.JSONDecodeError, OSError):
            return
        if isinstance(payload, dict):
            keywords = payload.get("recent_keywords")
            videos = payload.get("recent_videos")
            favorites = payload.get("favorite_videos")
            watch_later = payload.get("watch_later_videos")
            if isinstance(keywords, list):
                normalized_keywords: list[str] = []
                for item in keywords:
                    normalized = normalize_keyword(str(item))
                    if not normalized:
                        changed = True
                        continue
                    if normalized != str(item).strip():
                        changed = True
                    if normalized not in normalized_keywords:
                        normalized_keywords.append(normalized)
                self._data["recent_keywords"] = normalized_keywords[: self.max_items]
            if isinstance(videos, list):
                self._data["recent_videos"] = [item for item in videos if isinstance(item, dict)][: self.max_items]
            if isinstance(favorites, list):
                normalized_favorites: list[dict[str, Any]] = []
                seen_keys: set[str] = set()
                for item in favorites:
                    if not isinstance(item, dict):
                        changed = True
                        continue
                    key = video_key_from_payload(item)
                    if key is None or key in seen_keys:
                        changed = True
                        continue
                    seen_keys.add(key)
                    normalized_favorites.append(item)
                self._data["favorite_videos"] = normalized_favorites[: self.max_favorites]
            if isinstance(watch_later, list):
                normalized_watch_later: list[dict[str, Any]] = []
                seen_keys: set[str] = set()
                for item in watch_later:
                    if not isinstance(item, dict):
                        changed = True
                        continue
                    key = video_key_from_payload(item)
                    if key is None or key in seen_keys:
                        changed = True
                        continue
                    seen_keys.add(key)
                    normalized_watch_later.append(item)
                if len(normalized_watch_later) > self.max_watch_later:
                    changed = True
                self._data["watch_later_videos"] = normalized_watch_later[: self.max_watch_later]
        if changed:
            self.save()

    def save(self) -> None:
        directory = os.path.dirname(self.path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump(self._data, handle, ensure_ascii=False, indent=2)

    def add_keyword(self, keyword: str) -> None:
        cleaned = normalize_keyword(keyword)
        if not cleaned:
            return
        keywords = [item for item in self._data["recent_keywords"] if item != cleaned]
        keywords.insert(0, cleaned)
        self._data["recent_keywords"] = keywords[: self.max_items]
        self.save()

    def add_video(self, item: VideoItem) -> None:
        payload = item_to_history_payload(item)
        key = video_key_from_payload(payload)
        videos = [video for video in self._data["recent_videos"] if video_key_from_payload(video) != key]
        videos.insert(0, payload)
        self._data["recent_videos"] = videos[: self.max_items]
        self.save()

    def add_favorite(self, item: VideoItem) -> bool:
        payload = item_to_history_payload(item)
        key = video_key_from_payload(payload)
        if key is None:
            return False
        favorites = [video for video in self._data["favorite_videos"] if video_key_from_payload(video) != key]
        already_exists = len(favorites) != len(self._data["favorite_videos"])
        favorites.insert(0, payload)
        self._data["favorite_videos"] = favorites[: self.max_favorites]
        self.save()
        return not already_exists

    def remove_favorite(self, target: VideoItem | str) -> bool:
        key = target if isinstance(target, str) else video_key_from_item(target)
        if key is None:
            return False
        favorites = [video for video in self._data["favorite_videos"] if video_key_from_payload(video) != key]
        changed = len(favorites) != len(self._data["favorite_videos"])
        if changed:
            self._data["favorite_videos"] = favorites
            self.save()
        return changed

    def toggle_favorite(self, item: VideoItem) -> bool:
        if self.is_favorite(item):
            self.remove_favorite(item)
            return False
        self.add_favorite(item)
        return True

    def is_favorite(self, item: VideoItem | None) -> bool:
        key = video_key_from_item(item)
        if key is None:
            return False
        return any(video_key_from_payload(video) == key for video in self._data["favorite_videos"])

    def add_watch_later(self, item: VideoItem) -> bool:
        payload = item_to_history_payload(item)
        key = video_key_from_payload(payload)
        if key is None:
            return False
        watch_later = [video for video in self._data["watch_later_videos"] if video_key_from_payload(video) != key]
        already_exists = len(watch_later) != len(self._data["watch_later_videos"])
        watch_later.insert(0, payload)
        self._data["watch_later_videos"] = watch_later[: self.max_watch_later]
        self.save()
        return not already_exists

    def remove_watch_later(self, target: VideoItem | str) -> bool:
        key = target if isinstance(target, str) else video_key_from_item(target)
        if key is None:
            return False
        watch_later = [video for video in self._data["watch_later_videos"] if video_key_from_payload(video) != key]
        changed = len(watch_later) != len(self._data["watch_later_videos"])
        if changed:
            self._data["watch_later_videos"] = watch_later
            self.save()
        return changed

    def toggle_watch_later(self, item: VideoItem) -> bool:
        if self.is_watch_later(item):
            self.remove_watch_later(item)
            return False
        self.add_watch_later(item)
        return True

    def is_watch_later(self, item: VideoItem | None) -> bool:
        key = video_key_from_item(item)
        if key is None:
            return False
        return any(video_key_from_payload(video) == key for video in self._data["watch_later_videos"])

    def get_recent_keywords(self, limit: int = 10) -> list[str]:
        return list(self._data["recent_keywords"][:limit])

    def get_recent_videos(self, limit: int = 20) -> list[VideoItem]:
        return [item_from_payload(payload) for payload in self._data["recent_videos"][:limit]]

    def get_favorite_videos(self, limit: int | None = None) -> list[VideoItem]:
        payloads = self._data["favorite_videos"] if limit is None else self._data["favorite_videos"][:limit]
        return [item_from_payload(payload) for payload in payloads]

    def get_watch_later_videos(self, limit: int | None = None) -> list[VideoItem]:
        payloads = self._data["watch_later_videos"] if limit is None else self._data["watch_later_videos"][:limit]
        return [item_from_payload(payload) for payload in payloads]


class BilibiliClient:
    def __init__(self, timeout: int = DEFAULT_TIMEOUT, user_agent: str = DEFAULT_USER_AGENT) -> None:
        self.timeout = timeout
        self.user_agent = user_agent
        self.cookie_jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cookie_jar))
        self.comment_wbi_keys: dict[str, tuple[str, str]] = {}

    def _build_headers(self, referer: str, accept: str = "application/json, text/plain, */*") -> dict[str, str]:
        parsed_referer = urllib.parse.urlparse(referer)
        origin = f"{parsed_referer.scheme}://{parsed_referer.netloc}" if parsed_referer.scheme and parsed_referer.netloc else referer
        return {
            "User-Agent": self.user_agent,
            "Accept": accept,
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Origin": origin,
            "Referer": referer,
        }

    def _open(self, request: urllib.request.Request) -> Any:
        return self.opener.open(request, timeout=self.timeout)

    def _warmup(self, referer: str) -> None:
        warmup_targets = ["https://www.bilibili.com/"]
        if referer not in warmup_targets:
            warmup_targets.append(referer)
        for target in warmup_targets:
            request = urllib.request.Request(target, headers=self._build_headers(target, accept="text/html,application/xhtml+xml"))
            with self._open(request) as response:
                response.read()

    def _request_text(self, url: str, referer: str, accept: str = "text/html,application/xhtml+xml") -> str:
        for attempt in range(2):
            request = urllib.request.Request(url, headers=self._build_headers(referer, accept=accept))
            try:
                with self._open(request) as response:
                    return decode_response_body(response.read(), response.headers.get("Content-Encoding"))
            except urllib.error.HTTPError as exc:
                if exc.code == 412 and attempt == 0:
                    self._warmup(referer)
                    continue
                raise BilibiliAPIError(f"HTTP {exc.code}: {exc.reason}") from exc
            except urllib.error.URLError as exc:
                raise BilibiliAPIError(f"网络请求失败: {exc.reason}") from exc
        raise BilibiliAPIError("请求失败")

    def _request_json(self, url: str, params: dict[str, Any], referer: str) -> Any:
        query = urllib.parse.urlencode(params)
        for attempt in range(2):
            request = urllib.request.Request(
                f"{url}?{query}",
                headers=self._build_headers(referer),
            )
            try:
                with self._open(request) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                break
            except urllib.error.HTTPError as exc:
                if exc.code == 412 and attempt == 0:
                    self._warmup(referer)
                    continue
                raise BilibiliAPIError(f"HTTP {exc.code}: {exc.reason}") from exc
            except urllib.error.URLError as exc:
                raise BilibiliAPIError(f"网络请求失败: {exc.reason}") from exc
            except json.JSONDecodeError as exc:
                raise BilibiliAPIError("接口没有返回合法 JSON") from exc
        else:
            raise BilibiliAPIError("请求失败")

        code = payload.get("code")
        if code != 0:
            raise BilibiliAPIError(f"Bilibili 接口错误 code={code}: {payload.get('message', 'unknown')}")
        data = payload.get("data")
        if data is None:
            data = payload.get("result")
        return data if data is not None else {}

    def _video_page_state(self, bvid: str) -> dict[str, Any]:
        page_url = build_watch_url("bvid", bvid)
        html = self._request_text(page_url, "https://www.bilibili.com/")
        match = INITIAL_STATE_PATTERN.search(html) or INITIAL_STATE_FALLBACK_PATTERN.search(html)
        if not match:
            raise BilibiliAPIError("无法解析视频页状态")
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError as exc:
            raise BilibiliAPIError("视频页状态不是合法 JSON") from exc

    def _video_playinfo(self, page_url: str) -> dict[str, Any]:
        html = self._request_text(page_url, "https://www.bilibili.com/")
        match = PLAYINFO_PATTERN.search(html)
        if not match:
            raise BilibiliAPIError("无法解析视频播放信息")
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError as exc:
            raise BilibiliAPIError("视频播放信息不是合法 JSON") from exc

    def _comment_wbi_script_keys(self, bvid: str, force_refresh: bool = False) -> tuple[str, str]:
        state = self._video_page_state(bvid)
        abtest = state.get("abtest") or {}
        comment_hash = abtest.get("comment_version_hash")
        if comment_hash and force_refresh:
            self.comment_wbi_keys.pop(comment_hash, None)
        if comment_hash and comment_hash in self.comment_wbi_keys:
            return self.comment_wbi_keys[comment_hash]
        if comment_hash:
            script_url = f"https://s1.hdslb.com/bfs/seed/jinkela/commentpc/bili-comments.{comment_hash}.js"
            try:
                script = self._request_text(
                    script_url,
                    build_watch_url("bvid", bvid),
                    accept="text/javascript, application/javascript, */*",
                )
            except BilibiliAPIError:
                script = ""
            match = COMMENT_WBI_KEYS_PATTERN.search(script)
            if match:
                keys = (match.group(1), match.group(2))
                self.comment_wbi_keys[comment_hash] = keys
                return keys

        default_wbi_key = state.get("defaultWbiKey") or {}
        if default_wbi_key.get("wbiImgKey") and default_wbi_key.get("wbiSubKey"):
            return (default_wbi_key["wbiImgKey"], default_wbi_key["wbiSubKey"])
        raise BilibiliAPIError("无法解析评论接口签名参数")

    def _comments_via_wbi(self, oid: int, bvid: str, referer: str, force_refresh: bool = False) -> dict[str, Any]:
        img_key, sub_key = self._comment_wbi_script_keys(bvid, force_refresh=force_refresh)
        params = sign_wbi_params(
            {
                "oid": oid,
                "type": 1,
                "mode": 3,
                "pagination_str": json.dumps({"offset": ""}, separators=(",", ":")),
                "plat": 1,
                "web_location": COMMENT_WEB_LOCATION,
            },
            img_key,
            sub_key,
        )
        return self._request_json(
            "https://api.bilibili.com/x/v2/reply/wbi/main",
            params,
            referer,
        )

    def popular(self, page: int = 1, page_size: int = 10) -> list[VideoItem]:
        data = self._request_json(
            "https://api.bilibili.com/x/web-interface/popular",
            {"pn": page, "ps": page_size},
            "https://www.bilibili.com/",
        )
        return [item_from_payload(item) for item in data.get("list", [])]

    def recommend(self, page: int = 1, page_size: int = 10) -> list[VideoItem]:
        data = self._request_json(
            "https://api.bilibili.com/x/web-interface/index/top/feed/rcmd",
            {
                "fresh_idx": page,
                "fresh_type": 3,
                "feed_version": "SEO_VIDEO",
                "homepage_ver": 1,
                "brush": 0,
                "y_num": 5,
                "ps": page_size,
            },
            "https://www.bilibili.com/",
        )
        return [item_from_payload(item) for item in data.get("item", []) if item.get("goto") == "av"]

    def precious(self, page: int = 1, page_size: int = 10) -> list[VideoItem]:
        data = self._request_json(
            "https://api.bilibili.com/x/web-interface/popular/precious",
            {"page": page, "page_size": page_size},
            "https://www.bilibili.com/",
        )
        items = data.get("list", [])
        start = max(0, (page - 1) * page_size)
        return [item_from_payload(item) for item in items[start : start + page_size]]

    def region_ranking(self, rid: int, day: int = 3, page: int = 1, page_size: int = 10) -> list[VideoItem]:
        data = self._request_json(
            "https://api.bilibili.com/x/web-interface/ranking/region",
            {"rid": rid, "day": day, "original": 0},
            "https://www.bilibili.com/",
        )
        start = max(0, (page - 1) * page_size)
        return [item_from_payload(item) for item in data[start : start + page_size]]

    def bangumi(
        self,
        category: str = "番剧",
        *,
        index: bool = False,
        area: str | None = None,
        page: int = 1,
        page_size: int = 10,
    ) -> list[VideoItem]:
        meta = resolve_bangumi_category(category)
        season_type = int(meta["season_type"])
        if index:
            data = self._request_json(
                "https://api.bilibili.com/pgc/season/index/result",
                {"season_type": season_type, "page": page, "pagesize": page_size, "type": 1},
                "https://www.bilibili.com/anime/index/",
            )
            raw_items = list(data.get("list") or [])
        else:
            data = self._request_json(
                "https://api.bilibili.com/pgc/web/timeline/v2",
                {"season_type": season_type, "day_before": 0, "day_after": 6},
                "https://www.bilibili.com/anime/timeline/",
            )
            candidates: list[dict[str, Any]] = []
            candidates.extend(item for item in data.get("latest") or [] if isinstance(item, dict))
            for timeline_entry in data.get("timeline") or []:
                if not isinstance(timeline_entry, dict):
                    continue
                for item in timeline_entry.get("episodes") or timeline_entry.get("seasons") or []:
                    if isinstance(item, dict):
                        candidates.append(item)

            raw_items = []
            seen_urls: set[str] = set()
            for item in candidates:
                url = build_video_url(item)
                if url in seen_urls:
                    continue
                seen_urls.add(url)
                raw_items.append(item)
            start = max(0, (page - 1) * page_size)
            raw_items = raw_items[start : start + page_size]

        items = [item_from_bangumi_payload(item, category_label=str(meta["label"])) for item in raw_items]
        if area:
            keyword = area.strip()
            filtered = [
                item for item in items if keyword in item.title or keyword in item.author or keyword in item.description
            ]
            if filtered:
                items = filtered
        return items[:page_size]

    def search(self, keyword: str, page: int = 1, page_size: int = 10) -> list[VideoItem]:
        search_referer = f"https://search.bilibili.com/all?keyword={urllib.parse.quote(keyword)}"
        data = self._request_json(
            "https://api.bilibili.com/x/web-interface/search/type",
            {
                "search_type": "video",
                "keyword": keyword,
                "page": page,
            },
            search_referer,
        )
        items = [item_from_payload(item) for item in data.get("result", []) if item.get("type") == "video"]
        return items[:page_size]

    def video(self, ref: str) -> VideoItem:
        key, value = parse_video_ref(ref)
        data = self._request_json(
            "https://api.bilibili.com/x/web-interface/view",
            {key: value},
            "https://www.bilibili.com/",
        )
        return item_from_payload(data)

    def _bangumi_playinfo(self, item: VideoItem) -> dict[str, Any]:
        referer = item.url or "https://www.bilibili.com/bangumi/"
        episode_id = bangumi_episode_id_from_item(item)
        if episode_id is None:
            raise BilibiliAPIError("当前番剧条目缺少 EP 标识，无法解析音频流")
        return self._request_json(
            "https://api.bilibili.com/pgc/player/web/playurl",
            {"ep_id": episode_id, "fnval": 4048, "fourk": 1},
            referer,
        )

    def audio_stream_for_item(self, item: VideoItem) -> AudioStream:
        detail_item = item
        if not detail_item.bvid:
            referer = detail_item.url or ""
            if referer and "/bangumi/" in referer:
                playinfo = self._bangumi_playinfo(detail_item)
                return extract_audio_stream(
                    playinfo,
                    referer=referer,
                    user_agent=self.user_agent,
                    title=detail_item.title,
                )
            ref = detail_item.bvid or (str(detail_item.aid) if detail_item.aid is not None else "")
            if not ref:
                raise BilibiliAPIError("当前视频缺少 BV 号，无法解析音频流")
            detail_item = self.video(ref)
        if not detail_item.bvid:
            raise BilibiliAPIError("当前视频缺少 BV 号，无法解析音频流")
        referer = detail_item.url or build_watch_url("bvid", detail_item.bvid)
        playinfo = self._video_playinfo(referer)
        return extract_audio_stream(
            playinfo,
            referer=referer,
            user_agent=self.user_agent,
            title=detail_item.title,
        )

    def audio_stream(self, ref: str) -> AudioStream:
        return self.audio_stream_for_item(self.video(ref))

    def search_default(self) -> str:
        data = self._request_json(
            "https://api.bilibili.com/x/web-interface/wbi/search/default",
            {},
            "https://www.bilibili.com/",
        )
        return compact_whitespace(data.get("show_name") or data.get("name") or "")

    def trending_keywords(self, limit: int = 8) -> list[str]:
        data = self._request_json(
            "https://api.bilibili.com/x/web-interface/search/square",
            {"limit": limit, "from_source": "home_search"},
            "https://www.bilibili.com/",
        )
        trending = (data.get("trending") or {}).get("list", [])
        return [compact_whitespace(item.get("show_name") or item.get("keyword") or "") for item in trending if compact_whitespace(item.get("show_name") or item.get("keyword") or "")]

    def comments(self, oid: int, page_size: int = 4, bvid: str | None = None) -> list[CommentItem]:
        referer = f"https://www.bilibili.com/video/{bvid}" if bvid else f"https://www.bilibili.com/video/av{oid}"
        try:
            if bvid:
                for attempt in range(2):
                    try:
                        data = self._comments_via_wbi(oid, bvid, referer, force_refresh=attempt > 0)
                        break
                    except BilibiliAPIError as exc:
                        if attempt == 0 and "访问权限不足" in str(exc):
                            continue
                        raise
            else:
                data = self._request_json(
                    "https://api.bilibili.com/x/v2/reply/main",
                    {"next": 0, "type": 1, "oid": oid, "mode": 3, "ps": page_size},
                    referer,
                )
        except BilibiliAPIError as exc:
            if "访问权限不足" in str(exc) or "HTTP 412" in str(exc):
                raise BilibiliAPIError("评论接口受限，请稍后重试或按 o 在浏览器中查看") from exc
            raise
        return comments_from_thread_payload(data, page_size)


def build_detail_lines(item: VideoItem, width: int) -> list[str]:
    title_lines = wrap_display(item.title, width=max(20, width))
    description_lines = wrap_display(item.description, width=max(20, width)) if item.description else ["无简介"]
    return [
        *title_lines,
        "",
        f"👤 UP主: {item.author}",
        f"🔗 BV号: {item.bvid or '-'}",
        f"🔗 AID: {item.aid or '-'}",
        f"🕒 时长: {item.duration}",
        f"📅 发布时间: {format_timestamp(item.pubdate)}",
        f"▶ 播放: {human_count(item.play)}",
        f"≡ 弹幕: {human_count(item.danmaku)}",
        f"👍 点赞: {human_count(item.like)}",
        f"⭐ 收藏: {human_count(item.favorite)}",
        f"🌐 链接: {item.url}",
        "",
        "📝 简介:",
        *description_lines,
    ]


def comments_from_payload(payload: list[dict[str, Any]]) -> list[CommentItem]:
    comments: list[CommentItem] = []
    for item in payload:
        member = item.get("member") or {}
        content = item.get("content") or {}
        comments.append(
            CommentItem(
                author=member.get("uname") or "-",
                message=compact_whitespace(content.get("message") or ""),
                like=int(item.get("like") or 0),
                ctime=item.get("ctime"),
            )
        )
    return comments


def comments_from_thread_payload(payload: dict[str, Any], limit: int) -> list[CommentItem]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for field in ("top_replies", "replies"):
        for item in payload.get(field) or []:
            key = str(item.get("rpid_str") or item.get("rpid") or len(merged))
            if key in seen:
                continue
            seen.add(key)
            merged.append(item)
            if len(merged) >= limit:
                return comments_from_payload(merged)
    return comments_from_payload(merged)


def build_audio_worker_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="BiliTerminal internal audio worker.")
    subparsers = parser.add_subparsers(dest="command")
    audio_worker_parser = subparsers.add_parser("audio-worker", help=argparse.SUPPRESS)
    audio_worker_parser.add_argument("--url", required=True, help=argparse.SUPPRESS)
    audio_worker_parser.add_argument("--referer", required=True, help=argparse.SUPPRESS)
    audio_worker_parser.add_argument("--user-agent", required=True, help=argparse.SUPPRESS)
    audio_worker_parser.add_argument("--title", default="", help=argparse.SUPPRESS)
    return parser


def run_audio_worker_command(args: argparse.Namespace) -> int:
    if args.command == "audio-worker":
        return run_audio_worker(args.url, args.referer, args.user_agent, args.title)
    print("BiliTerminal core only exposes the internal audio-worker command.", file=sys.stderr)
    return 2


def main(argv: list[str] | None = None) -> int:
    parser = build_audio_worker_parser()
    args = parser.parse_args(argv)
    try:
        return run_audio_worker_command(args)
    except (BilibiliAPIError, ValueError) as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
