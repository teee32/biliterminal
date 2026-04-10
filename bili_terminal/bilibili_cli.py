#!/usr/bin/env python3
from __future__ import annotations

import argparse
import cmd
import datetime as dt
import gzip
import hashlib
import http.cookiejar
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import textwrap
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
import zlib
from dataclasses import dataclass
from typing import Any


DEFAULT_TIMEOUT = 15
DEFAULT_STATE_DIR = ".omx/state"
DEFAULT_HISTORY_FILENAME = "bilibili-cli-history.json"
MAX_HISTORY_ITEMS = 40
MAX_FAVORITE_ITEMS = 200
MACOS_AUDIO_HELPER_NAME = "biliterminal-audio-helper"
BILIBILI_PINK_RGB = (984, 447, 600)
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
class ListState:
    mode: str
    page: int
    keyword: str
    selected_index: int
    channel_index: int


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


def add_rank_arguments(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    parser.add_argument("region", nargs="?", help="分区名，如 动画 / 音乐 / 游戏 / 影视")
    parser.add_argument("--rid", type=int, help="分区 ID，优先级高于分区名")
    parser.add_argument("--day", type=int, choices=(1, 3, 7), default=3, help="排行周期天数")
    parser.add_argument("-p", "--page", type=int, default=1, help="页码")
    parser.add_argument("-n", "--limit", type=int, default=10, help="数量")
    return parser


def build_rank_argument_parser(*, prog: str = "rank", add_help: bool = False) -> argparse.ArgumentParser:
    return add_rank_arguments(argparse.ArgumentParser(prog=prog, add_help=add_help))


def add_bangumi_arguments(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    parser.add_argument("category", nargs="?", default="番剧", help="分类：番剧 / 国创 / 影视")
    parser.add_argument("--index", action="store_true", help="切到索引模式")
    parser.add_argument("--area", help="地区筛选（当前优先用于索引/展示）")
    parser.add_argument("-p", "--page", type=int, default=1, help="页码")
    parser.add_argument("-n", "--limit", type=int, default=10, help="数量")
    return parser


def build_bangumi_argument_parser(*, prog: str = "bangumi", add_help: bool = False) -> argparse.ArgumentParser:
    return add_bangumi_arguments(argparse.ArgumentParser(prog=prog, add_help=add_help))


def open_video_target(target: str) -> str:
    ref_type, value = parse_video_ref(target)
    url = build_watch_url(ref_type, value)
    webbrowser.open(url)
    return url


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
    command = [
        sys.executable,
        os.path.abspath(__file__),
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
    ) -> None:
        self.path = path or default_history_path()
        self.max_items = max_items
        self.max_favorites = max_favorites
        self._data: dict[str, list[Any]] = {
            "recent_keywords": [],
            "recent_videos": [],
            "favorite_videos": [],
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

    def get_recent_keywords(self, limit: int = 10) -> list[str]:
        return list(self._data["recent_keywords"][:limit])

    def get_recent_videos(self, limit: int = 20) -> list[VideoItem]:
        return [item_from_payload(payload) for payload in self._data["recent_videos"][:limit]]

    def get_favorite_videos(self, limit: int | None = None) -> list[VideoItem]:
        payloads = self._data["favorite_videos"] if limit is None else self._data["favorite_videos"][:limit]
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


class BilibiliCLI(cmd.Cmd):
    intro = (
        "Bilibili CLI 已启动。\n"
        "可用命令: hot [页码] [数量], search <关键词> [页码] [数量], "
        "rank [分区|--rid] [--day] [--page] [--limit], bangumi [分类] [--index] [--area] [--page] [--limit], "
        "video <BV号|av号|URL|序号>, audio <序号|BV号|URL|pause|resume|toggle|stop>, "
        "favorite <序号|BV号|URL>, favorites [open|remove], open <序号|BV号|URL>, exit"
    )
    prompt = "bili> "

    def __init__(self, client: BilibiliClient, history_store: HistoryStore | None = None) -> None:
        super().__init__()
        self.client = client
        self.history_store = history_store or HistoryStore()
        self.last_items: list[VideoItem] = []

    def emptyline(self) -> bool:
        return False

    def do_hot(self, arg: str) -> None:
        parts = shlex.split(arg)
        page = int(parts[0]) if len(parts) >= 1 else 1
        limit = int(parts[1]) if len(parts) >= 2 else 10
        items = self.client.popular(page=page, page_size=limit)
        self.last_items = items
        print_video_list(items, f"热门视频 第 {page} 页")

    def do_search(self, arg: str) -> None:
        parts = shlex.split(arg)
        if not parts:
            print("用法: search <关键词> [页码] [数量]")
            return
        page = 1
        limit = 10
        if len(parts) >= 2 and parts[-1].isdigit():
            limit = int(parts.pop())
        if len(parts) >= 2 and parts[-1].isdigit():
            page = int(parts.pop())
        keyword = " ".join(parts)
        items = self.client.search(keyword=keyword, page=page, page_size=limit)
        self.history_store.add_keyword(keyword)
        self.last_items = items
        print_video_list(items, f"搜索结果: {keyword} | 第 {page} 页")

    def do_rank(self, arg: str) -> None:
        try:
            args = build_rank_argument_parser().parse_args(shlex.split(arg))
            rid, label = resolve_region_rid(args.region, args.rid)
        except SystemExit:
            print("用法: rank [分区名] [--rid RID] [--day 1|3|7] [--page N] [--limit N]")
            return
        except ValueError as exc:
            print(str(exc))
            return
        items = self.client.region_ranking(rid=rid, day=args.day, page=args.page, page_size=args.limit)
        self.last_items = items
        print_video_list(items, f"{label} 排行榜 | 第 {args.page} 页")

    def do_ranking(self, arg: str) -> None:
        self.do_rank(arg)

    def do_bangumi(self, arg: str) -> None:
        try:
            args = build_bangumi_argument_parser().parse_args(shlex.split(arg))
        except SystemExit:
            print("用法: bangumi [分类] [--index] [--area 地区] [--page N] [--limit N]")
            return
        meta = resolve_bangumi_category(args.category)
        items = self.client.bangumi(
            category=str(meta["label"]),
            index=args.index,
            area=args.area,
            page=args.page,
            page_size=args.limit,
        )
        self.last_items = items
        print_video_list(items, build_bangumi_title(str(meta["label"]), index=args.index, page=args.page, area=args.area))

    def do_video(self, arg: str) -> None:
        target = arg.strip()
        if not target:
            print("用法: video <BV号|av号|URL|序号>")
            return
        if target.isdigit() and self.last_items:
            index = int(target) - 1
            if index < 0 or index >= len(self.last_items):
                raise ValueError(f"序号超出范围: {target}")
            last_item = self.last_items[index]
            if not last_item.bvid and last_item.aid is None:
                self.history_store.add_video(last_item)
                print_video_detail(last_item)
                return
        item = self.client.video(self._resolve_target(target))
        self.history_store.add_video(item)
        print_video_detail(item)

    def do_history(self, _: str) -> None:
        self.last_items = self.history_store.get_recent_videos(10)
        print_history(self.history_store)

    def do_favorite(self, arg: str) -> None:
        if not arg.strip():
            print("用法: favorite <序号|BV号|av号|URL>")
            return
        item = self._resolve_item_for_favorite(arg.strip())
        added = self.history_store.add_favorite(item)
        status = "已收藏" if added else "收藏夹已更新"
        print(f"{status}: {item.title}")

    def do_favorites(self, arg: str) -> None:
        parts = shlex.split(arg)
        if not parts:
            favorites = self.history_store.get_favorite_videos()
            self.last_items = favorites
            print_favorites(self.history_store)
            return
        action = parts[0].lower()
        if action == "open" and len(parts) >= 2:
            item = self._resolve_favorite_item(parts[1])
            webbrowser.open(item.url)
            self.history_store.add_video(item)
            print(f"已打开收藏: {item.url}")
            return
        if action == "remove" and len(parts) >= 2:
            item = self._resolve_favorite_item(parts[1])
            self.history_store.remove_favorite(item)
            print(f"已移出收藏: {item.title}")
            return
        print("用法: favorites [open <序号|BV号|av号|URL> | remove <序号|BV号|av号|URL>]")

    def do_comments(self, arg: str) -> None:
        if not arg.strip():
            print("用法: comments <BV号|av号|URL|序号> [数量]")
            return
        parts = shlex.split(arg)
        limit = 5
        if parts[-1].isdigit():
            limit = int(parts.pop())
        target = self._resolve_target(" ".join(parts))
        item = self.client.video(target)
        if item.aid is None:
            raise ValueError("当前视频缺少 AID，无法加载评论")
        comments = self.client.comments(item.aid, page_size=limit, bvid=item.bvid)
        print_comments(item, comments)

    def do_open(self, arg: str) -> None:
        if not arg.strip():
            print("用法: open <序号|BV号|URL>")
            return
        target = arg.strip()
        if target.isdigit() and self.last_items:
            index = int(target) - 1
            if index < 0 or index >= len(self.last_items):
                print(f"序号超出范围: {target}")
                return
            item = self.last_items[index]
            self.history_store.add_video(item)
            url = item.url
        else:
            try:
                key, value = parse_video_ref(target)
                url = build_watch_url(key, value)
            except ValueError:
                url = target
        webbrowser.open(url)
        print(f"已打开: {url}")

    def do_audio(self, arg: str) -> None:
        if not arg.strip():
            print("用法: audio <序号|BV号|av号|URL|pause|resume|toggle|stop>")
            return
        action = arg.strip().lower()
        if action == "pause":
            print(pause_audio_playback())
            return
        if action == "resume":
            print(resume_audio_playback())
            return
        if action == "toggle":
            print(toggle_audio_playback())
            return
        if action == "stop":
            print(stop_audio_playback())
            return
        item = self._resolve_item_for_favorite(arg.strip())
        self.history_store.add_video(item)
        print(play_audio_for_item(self.client, item))

    def do_exit(self, _: str) -> bool:
        return True

    def do_quit(self, _: str) -> bool:
        return True

    def do_EOF(self, _: str) -> bool:
        print()
        return True

    def _resolve_target(self, target: str) -> str:
        if target.isdigit() and self.last_items:
            index = int(target) - 1
            if index < 0 or index >= len(self.last_items):
                raise ValueError(f"序号超出范围: {target}")
            item = self.last_items[index]
            return item.bvid or str(item.aid)
        return target

    def _resolve_item_for_favorite(self, target: str) -> VideoItem:
        if target.isdigit() and self.last_items:
            index = int(target) - 1
            if index < 0 or index >= len(self.last_items):
                raise ValueError(f"序号超出范围: {target}")
            return self.last_items[index]
        return self.client.video(self._resolve_target(target))

    def _resolve_favorite_item(self, target: str) -> VideoItem:
        favorites = self.history_store.get_favorite_videos()
        if target.isdigit():
            index = int(target) - 1
            if index < 0 or index >= len(favorites):
                raise ValueError(f"收藏夹序号超出范围: {target}")
            return favorites[index]
        ref_type, value = parse_video_ref(target)
        target_key = video_key_from_ref(ref_type, value)
        for item in favorites:
            if video_key_from_item(item) == target_key:
                return item
        raise ValueError("收藏夹中不存在该视频")

    def onecmd(self, line: str) -> bool:
        try:
            return super().onecmd(line)
        except (BilibiliAPIError, ValueError) as exc:
            print(f"错误: {exc}")
            return False


def print_video_list(items: list[VideoItem], title: str) -> None:
    print(f"\n{title}")
    print("=" * len(title))
    if not items:
        print("没有结果。")
        return
    for index, item in enumerate(items, start=1):
        meta = (
            f"UP: {item.author} | 播放: {human_count(item.play)} | "
            f"弹幕: {human_count(item.danmaku)} | 时长: {item.duration} | "
            f"发布时间: {format_timestamp(item.pubdate)}"
        )
        print(f"{index:>2}. {shorten(item.title, 72)}")
        print(f"    {meta}")
        print(f"    {item_ref_label(item)} | {item.url}")
    print("\n提示: 可用 `video 1` 查看详情，`audio 1` 播放音频，`favorite 1` 加入收藏，或 `open 1` 在浏览器中打开。")


def print_video_detail(item: VideoItem) -> None:
    print(f"\n{item.title}")
    print("=" * len(item.title))
    print(f"UP主: {item.author}")
    print(f"BV号: {item.bvid or '-'}")
    print(f"AID: {item.aid or '-'}")
    print(f"时长: {item.duration}")
    print(f"发布时间: {format_timestamp(item.pubdate)}")
    print(f"播放: {human_count(item.play)}  弹幕: {human_count(item.danmaku)}")
    print(f"点赞: {human_count(item.like)}  收藏: {human_count(item.favorite)}")
    print(f"链接: {item.url}")
    if item.description:
        print("\n简介:")
        print(textwrap.fill(item.description, width=88))


def print_history(history_store: HistoryStore) -> None:
    print("\n最近搜索")
    print("========")
    keywords = history_store.get_recent_keywords(10)
    if keywords:
        for index, keyword in enumerate(keywords, start=1):
            print(f"{index:>2}. {keyword}")
    else:
        print("没有搜索记录。")

    print("\n最近浏览")
    print("========")
    videos = history_store.get_recent_videos(10)
    if not videos:
        print("没有视频记录。")
        return
    for index, item in enumerate(videos, start=1):
        print(f"{index:>2}. {shorten(item.title, 72)}")
        print(f"    {item.author} | {item.bvid or item.aid} | {item.url}")


def print_favorites(history_store: HistoryStore) -> None:
    print("\n收藏夹")
    print("======")
    favorites = history_store.get_favorite_videos()
    if not favorites:
        print("收藏夹为空。")
        return
    for index, item in enumerate(favorites, start=1):
        print(f"{index:>2}. {shorten(item.title, 72)}")
        print(f"    {item.author} | {item.bvid or item.aid} | {item.url}")
    print("\n提示: 可用 `audio 1` 播放音频，`favorites open 1` 直接打开，或 `favorites remove 1` 从收藏夹移除。")


def print_comments(item: VideoItem, comments: list[CommentItem]) -> None:
    title = f"热评预览: {shorten(item.title, 72)}"
    print(f"\n{title}")
    print("=" * len(title))
    if not comments:
        print("没有可显示的评论。")
        return
    for index, comment in enumerate(comments, start=1):
        print(f"{index:>2}. {comment.author} | {human_count(comment.like)} 赞 | {format_timestamp(comment.ctime)}")
        print(textwrap.fill(comment.message or "暂无评论内容", width=88, initial_indent="    ", subsequent_indent="    "))


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


class BilibiliTUI:
    def __init__(self, client: BilibiliClient, history_store: HistoryStore, limit: int = 5) -> None:
        self.client = client
        self.history_store = history_store
        self.limit = limit
        self.mode = "hot"
        self.page = 1
        self.keyword = ""
        self.items: list[VideoItem] = []
        self.selected_index = 0
        self.status = "正在加载..."
        self.detail_cache: dict[str, VideoItem] = {}
        self.list_stack: list[ListState] = []
        self.detail_mode = False
        self.detail_scroll = 0
        self.show_help = False
        self.use_colors = False
        self.channels = HOME_CHANNELS
        self.channel_index = 0
        self.default_search_keyword = ""
        self.trending_keywords_cache: list[str] = []
        self.comment_cache: dict[str, list[CommentItem]] = {}
        self.comment_errors: dict[str, str] = {}
        self.comment_loaded: set[str] = set()

    def init_theme(self) -> None:
        import curses

        if not curses.has_colors():
            self.use_colors = False
            return
        curses.start_color()
        curses.use_default_colors()
        theme_color = 13 if getattr(curses, "COLORS", 0) >= 16 else curses.COLOR_MAGENTA
        if curses.can_change_color() and theme_color < getattr(curses, "COLORS", 0):
            try:
                curses.init_color(theme_color, *BILIBILI_PINK_RGB)
            except curses.error:
                pass
        curses.init_pair(1, curses.COLOR_WHITE, theme_color)
        curses.init_pair(2, theme_color, -1)
        curses.init_pair(3, curses.COLOR_WHITE, -1)
        curses.init_pair(4, curses.COLOR_BLACK, theme_color)
        self.use_colors = True

    def attr_header(self) -> int:
        import curses

        return curses.color_pair(1) | curses.A_BOLD if self.use_colors else curses.A_REVERSE

    def attr_accent(self) -> int:
        import curses

        return curses.color_pair(2) | curses.A_BOLD if self.use_colors else curses.A_BOLD

    def attr_title(self) -> int:
        import curses

        return curses.color_pair(3) | curses.A_BOLD if self.use_colors else curses.A_BOLD

    def attr_selected(self) -> int:
        import curses

        return curses.color_pair(4) | curses.A_BOLD if self.use_colors else curses.A_REVERSE

    def attr_muted(self) -> int:
        import curses

        return curses.A_DIM

    @property
    def selected_item(self) -> VideoItem | None:
        if not self.items:
            return None
        return self.items[self.selected_index]

    @property
    def title(self) -> str:
        if self.mode == "search":
            return f"搜索: {self.keyword}  第 {self.page} 页"
        if self.mode == "history":
            return "最近浏览"
        if self.mode == "favorites":
            return "收藏夹"
        return f"{self.active_channel()['label']}  第 {self.page} 页"

    def active_channel(self) -> dict[str, Any]:
        return self.channels[self.channel_index]

    def _cache_key(self, item: VideoItem | None) -> str | None:
        if item is None:
            return None
        if item.bvid:
            return item.bvid
        if item.aid is not None:
            return str(item.aid)
        return item.url or None

    def current_detail_item(self) -> VideoItem | None:
        item = self.selected_item
        key = self._cache_key(item)
        if key and key in self.detail_cache:
            return self.detail_cache[key]
        return item

    def current_comments(self) -> list[CommentItem]:
        key = self._cache_key(self.selected_item)
        if key is None:
            return []
        return self.comment_cache.get(key, [])

    def current_comment_error(self) -> str | None:
        key = self._cache_key(self.selected_item)
        if key is None:
            return None
        return self.comment_errors.get(key)

    def current_comments_loaded(self) -> bool:
        key = self._cache_key(self.selected_item)
        if key is None:
            return False
        return key in self.comment_loaded

    def current_list_state(self) -> ListState:
        return ListState(
            mode=self.mode,
            page=self.page,
            keyword=self.keyword,
            selected_index=self.selected_index,
            channel_index=self.channel_index,
        )

    def push_list_state(self) -> None:
        state = self.current_list_state()
        if not self.list_stack or self.list_stack[-1] != state:
            self.list_stack.append(state)
        self.list_stack = self.list_stack[-20:]

    def restore_previous_state(self) -> None:
        if not self.list_stack:
            self.status = "没有可返回的列表状态"
            return
        state = self.list_stack.pop()
        self.mode = state.mode
        self.page = state.page
        self.keyword = state.keyword
        self.selected_index = state.selected_index
        self.channel_index = state.channel_index
        self.detail_mode = False
        self.load_items()
        self.selected_index = min(self.selected_index, max(0, len(self.items) - 1))
        self.status = f"已返回: {self.title}"

    def clamp_selection(self) -> None:
        if not self.items:
            self.selected_index = 0
            return
        self.selected_index = max(0, min(self.selected_index, len(self.items) - 1))

    def clamp_detail_scroll(self, width: int, height: int) -> None:
        lines = self.get_detail_lines(max(20, width))
        max_scroll = max(0, len(lines) - height)
        self.detail_scroll = max(0, min(self.detail_scroll, max_scroll))

    def get_detail_lines(self, width: int) -> list[str]:
        item = self.current_detail_item()
        if item is None:
            return ["没有结果。"]
        lines = build_detail_lines(item, width)
        comments = self.current_comments()
        comment_error = self.current_comment_error()
        if comment_error and not comments:
            lines.extend(["", f"评论加载失败: {comment_error}", "提示: 按 o 在浏览器中查看完整评论"])
        if comments:
            lines.extend(["", "💬 热评:"])
            for index, comment in enumerate(comments, start=1):
                header = f"{index}. 👤 {comment.author} · 👍 {human_count(comment.like)} · 📅 {format_timestamp(comment.ctime)}"
                lines.append(header)
                lines.extend(wrap_display(comment.message or "暂无评论内容", width=max(20, width)))
                lines.append("")
        return lines

    def refresh_home_meta(self, force: bool = False) -> None:
        if force or not self.default_search_keyword:
            try:
                self.default_search_keyword = self.client.search_default()
            except BilibiliAPIError:
                if not self.default_search_keyword:
                    self.default_search_keyword = ""
        if force or not self.trending_keywords_cache:
            try:
                self.trending_keywords_cache = self.client.trending_keywords(6)
            except BilibiliAPIError:
                if not self.trending_keywords_cache:
                    self.trending_keywords_cache = []

    def ensure_comments_for_selected(self, force: bool = False) -> None:
        item = self.selected_item
        key = self._cache_key(item)
        if item is None or key is None:
            return
        if not force and (key in self.comment_cache or key in self.comment_errors):
            return
        aid = item.aid
        referer_bvid = item.bvid
        if aid is None:
            detail_item = self.current_detail_item()
            if detail_item and detail_item.aid is not None:
                aid = detail_item.aid
                referer_bvid = detail_item.bvid or referer_bvid
            else:
                try:
                    detail_item = self.client.video(key)
                except BilibiliAPIError:
                    return
                self.detail_cache[key] = detail_item
                aid = detail_item.aid
                referer_bvid = detail_item.bvid or referer_bvid
        if aid is None:
            return
        try:
            self.comment_cache[key] = self.client.comments(aid, page_size=4, bvid=referer_bvid)
            self.comment_loaded.add(key)
            self.comment_errors.pop(key, None)
        except BilibiliAPIError as exc:
            self.comment_cache[key] = []
            self.comment_loaded.discard(key)
            self.comment_errors[key] = str(exc)

    def load_items(self, *, force_comments: bool = False) -> None:
        self.detail_mode = False
        self.detail_scroll = 0
        if self.mode == "search" and self.keyword:
            self.items = self.client.search(self.keyword, page=self.page, page_size=self.limit)
        elif self.mode == "history":
            self.items = self.history_store.get_recent_videos(self.limit)
        elif self.mode == "favorites":
            self.items = self.history_store.get_favorite_videos(self.limit)
        else:
            self.refresh_home_meta()
            channel = self.active_channel()
            source = channel["source"]
            if source == "recommend":
                self.items = self.client.recommend(page=self.page, page_size=self.limit)
            elif source == "popular":
                self.items = self.client.popular(page=self.page, page_size=self.limit)
            elif source == "precious":
                self.items = self.client.precious(page=self.page, page_size=self.limit)
            elif source == "bangumi":
                self.items = self.client.bangumi(
                    category=str(channel.get("category") or "番剧"),
                    index=bool(channel.get("index")),
                    area=channel.get("area"),
                    page=self.page,
                    page_size=self.limit,
                )
            else:
                self.items = self.client.region_ranking(channel["rid"], page=self.page, page_size=self.limit)
        self.clamp_selection()
        self.ensure_comments_for_selected(force=force_comments)
        self.status = f"已加载 {len(self.items)} 条结果"

    def switch_mode(self, mode: str, *, page: int | None = None, keyword: str | None = None, push_current: bool = True) -> None:
        if push_current:
            self.push_list_state()
        self.mode = mode
        self.page = page if page is not None else 1
        if keyword is not None:
            self.keyword = keyword
        self.selected_index = 0
        self.load_items()

    def set_channel(self, index: int, *, push_current: bool = True) -> None:
        index = max(0, min(index, len(self.channels) - 1))
        if self.mode != "hot":
            self.channel_index = index
            self.switch_mode("hot", page=1, push_current=push_current)
            return
        if push_current:
            self.push_list_state()
        self.channel_index = index
        self.page = 1
        self.selected_index = 0
        self.load_items()

    def cycle_channel(self, step: int) -> None:
        target = (self.channel_index + step) % len(self.channels)
        self.set_channel(target)

    def refresh_current_view(self) -> None:
        if self.mode == "hot":
            self.refresh_home_meta(force=True)
        self.load_items(force_comments=True)
        self.status = f"已刷新: {self.title}"

    def refresh_comments(self) -> None:
        if self.selected_item is None:
            self.status = "当前没有可加载评论的视频"
            return
        self.ensure_comments_for_selected(force=True)
        comment_error = self.current_comment_error()
        if comment_error:
            self.status = f"评论加载失败: {comment_error}"
            return
        comment_count = len(self.current_comments())
        self.status = f"已加载评论 {comment_count} 条"

    def toggle_selected_favorite(self) -> None:
        item = self.current_detail_item() if self.detail_mode else self.selected_item
        if item is None:
            self.status = "当前没有可收藏的视频"
            return
        is_added = self.history_store.toggle_favorite(item)
        message = f"{'已收藏' if is_added else '已取消收藏'}: {truncate_display(item.title, 40)}"
        if self.mode == "favorites":
            self.load_items()
        self.status = message

    def play_selected_audio(self) -> None:
        item = self.current_detail_item() if self.detail_mode else self.selected_item
        if item is None:
            self.status = "当前没有可播放音频的视频"
            return
        self.history_store.add_video(item)
        self.status = audio_action_for_item(self.client, item)

    def stop_audio(self) -> None:
        self.status = stop_audio_playback()

    def open_selected(self) -> None:
        item = self.selected_item
        if item is None:
            self.status = "当前没有可打开的视频"
            return
        self.history_store.add_video(item)
        webbrowser.open(item.url)
        self.status = f"已打开: {item.url}"

    def load_selected_detail(self, enter_detail_mode: bool = True) -> None:
        item = self.selected_item
        if item is None:
            self.status = "当前没有可查看的视频"
            return
        key = self._cache_key(item)
        if key is None:
            self.status = "当前视频缺少可查询标识"
            return
        if item.bvid or item.aid is not None:
            self.detail_cache[key] = self.client.video(key)
        else:
            self.detail_cache[key] = item
        self.history_store.add_video(self.detail_cache[key])
        self.detail_scroll = 0
        self.detail_mode = enter_detail_mode
        self.status = f"已加载详情: {item.title}"

    def rerun_last_search(self) -> None:
        keywords = self.history_store.get_recent_keywords(1)
        if not keywords:
            self.status = "没有最近搜索记录"
            return
        self.switch_mode("search", page=1, keyword=keywords[0])

    def prompt_input(self, stdscr: Any, prompt: str, initial: str = "") -> str | None:
        import curses

        height, width = stdscr.getmaxyx()
        buffer = initial
        curses.curs_set(1)
        while True:
            stdscr.move(height - 1, 0)
            stdscr.clrtoeol()
            text = f"{prompt}{buffer}"
            stdscr.addnstr(height - 1, 0, text, max(1, width - 1))
            stdscr.refresh()
            key = stdscr.get_wch()
            if key in ("\x1b",):
                curses.curs_set(0)
                return None
            if key in ("\n", "\r"):
                curses.curs_set(0)
                return buffer.strip()
            if key in (curses.KEY_BACKSPACE, "\b", "\x7f"):
                buffer = buffer[:-1]
                continue
            if isinstance(key, str) and key.isprintable():
                buffer += key

    def draw_help_overlay(self, stdscr: Any, height: int, width: int) -> None:
        import curses

        lines = [
            "帮助",
            "",
            "j / k, ↑ / ↓   移动选中项",
            "Enter          打开详情页",
            "Esc / b        返回",
            "/ 或 s         搜索，支持中文输入",
            "Tab / Shift+Tab 切换首页分区",
            "1-9            直接切换对应分区",
            "l              重跑最近一次搜索",
            "h              切回热门",
            "v              查看历史",
            "m              查看收藏夹",
            "f              收藏 / 取消收藏当前视频",
            "a              播放 / 暂停当前视频音频",
            "x              停止当前音频",
            "n / p          下一页 / 上一页",
            "o              浏览器打开当前视频",
            "c              刷新评论预览",
            "d              使用默认搜索词搜索",
            "r              刷新当前页",
            "?              显示或关闭帮助",
            "q              退出",
            "",
            f"最近搜索: {', '.join(self.history_store.get_recent_keywords(3)) or '无'}",
        ]
        box_width = min(width - 4, max(56, width * 3 // 4))
        box_height = min(height - 4, len(lines) + 2)
        start_y = max(1, (height - box_height) // 2)
        start_x = max(2, (width - box_width) // 2)
        win = stdscr.derwin(box_height, box_width, start_y, start_x)
        win.erase()
        if self.use_colors:
            win.bkgd(" ", self.attr_header())
        win.box()
        for index, line in enumerate(lines[: box_height - 2], start=1):
            attr = self.attr_title() if index == 1 else curses.A_NORMAL
            win.addnstr(index, 2, line, box_width - 4, attr)

    def draw_panel_title(self, stdscr: Any, y: int, x: int, text: str, max_width: int) -> None:
        label = f" {text} "
        stdscr.addnstr(y, x, label, max_width, self.attr_accent())

    def draw_box(self, stdscr: Any, y: int, x: int, height: int, width: int, label: str | None = None) -> None:
        import curses

        if height <= 1 or width <= 1:
            return

        top = "╭" + "─" * (width - 2) + "╮"
        bottom = "╰" + "─" * (width - 2) + "╯"
        
        try:
            stdscr.addnstr(y, x, top, width, self.attr_muted())
            for i in range(1, height - 1):
                stdscr.addnstr(y + i, x, "│", 1, self.attr_muted())
                stdscr.addnstr(y + i, x + width - 1, "│", 1, self.attr_muted())
            stdscr.addnstr(y + height - 1, x, bottom, width, self.attr_muted())
        except curses.error:
            pass

        if label:
            label_text = f" {label} "
            try:
                stdscr.addnstr(y, x + 2, label_text, width - 4, self.attr_accent())
            except curses.error:
                pass

    def draw_banner(self, stdscr: Any, y: int, width: int) -> int:
        banner_height = 6
        self.draw_box(stdscr, y, 0, banner_height, width, "发现")
        headline = "哔哩哔哩终端首页"
        stdscr.addnstr(y + 1, centered_x(width, headline, 2), headline, width - 4, self.attr_title())
        if self.mode == "search" and self.keyword:
            query = truncate_display(self.keyword, max(12, width - 24))
            search_text = f" 搜索中：{query} "
        else:
            default_word = self.default_search_keyword or "按 / 开始搜索"
            search_text = f" 默认搜索：{truncate_display(default_word, max(12, width - 24))} "
        search_x = centered_x(width, search_text, 2)
        stdscr.addnstr(y + 2, search_x, search_text, max(1, width - search_x - 2), self.attr_selected())
        if self.mode == "hot":
            channel_label = self.active_channel()["label"]
        elif self.mode == "favorites":
            channel_label = "收藏夹"
        elif self.mode == "history":
            channel_label = "最近浏览"
        else:
            channel_label = "搜索"
        section_line = f"当前分区 · {channel_label}"
        stdscr.addnstr(y + 3, centered_x(width, section_line, 2), section_line, width - 4, self.attr_accent())
        hot_words = " · ".join(self.trending_keywords_cache[:3]) if self.trending_keywords_cache else "热点内容 · 分区导航 · 精选视频"
        subline = f"热搜：{truncate_display(hot_words, max(16, width - 12))}"
        stdscr.addnstr(y + 4, centered_x(width, subline, 2), subline, width - 4, self.attr_muted())
        return banner_height

    def draw_category_row(self, stdscr: Any, y: int, width: int) -> int:
        chips = [f"[{index + 1}.{channel['label']}]" for index, channel in enumerate(self.channels)]
        x = 0
        for index, chip in enumerate(chips):
            chip_width = display_width(chip)
            if x + chip_width >= width - 1:
                break
            attr = self.attr_accent() if index == self.channel_index and self.mode == "hot" else self.attr_muted()
            stdscr.addnstr(y, x, chip, chip_width, attr)
            x += chip_width + 1
        return 1

    def selected_card_item(self) -> VideoItem | None:
        return self.selected_item

    def draw_featured_card(self, stdscr: Any, y: int, x: int, height: int, width: int, item: VideoItem | None, selected: bool) -> None:
        self.draw_box(stdscr, y, x, height, width, "今日精选")
        if item is None:
            stdscr.addnstr(y + 2, x + 2, "没有可展示的内容", width - 4, self.attr_muted())
            return

        title_text = f"★ {item.title}" if self.history_store.is_favorite(item) else item.title
        if height < 9:
            stdscr.addnstr(y + 1, x + 2, truncate_display(title_text, width - 4), width - 4, self.attr_title())
            stdscr.addnstr(y + 2, x + 2, truncate_display(item.author, width - 4), width - 4, self.attr_muted())
            stdscr.addnstr(y + height - 2, x + 2, "Enter 查看详情", width - 4, self.attr_muted())
            return

        title_attr = self.attr_selected() if selected else self.attr_title()
        title_lines = wrap_display(title_text, max(12, width - 4))
        content_y = y + 1
        max_title_lines = 2 if height < 16 else 3
        shown_title_lines = title_lines[:max_title_lines]
        for line in shown_title_lines:
            stdscr.addnstr(content_y, x + 2, line, width - 4, title_attr)
            content_y += 1

        meta_lines = [
            truncate_display(item.author, width - 4),
            truncate_display(f"{human_count(item.play)} 播放   {human_count(item.danmaku)} 弹幕", width - 4),
            truncate_display(f"{item.duration}   {format_timestamp(item.pubdate)}", width - 4),
            truncate_display(f"稿件号 {item.bvid or item.aid}", width - 4),
        ]
        for meta_line in meta_lines:
            stdscr.addnstr(content_y, x + 2, meta_line, width - 4, self.attr_muted())
            content_y += 1

        sections: list[tuple[str, list[str]]] = []
        desc_lines = wrap_display(item.description or "暂无简介", width=max(12, width - 4))
        sections.append(("简介", desc_lines))

        hot_lines = [f"{index + 1}. {word}" for index, word in enumerate(self.trending_keywords_cache[:6])]
        if hot_lines:
            sections.append(("热搜速览", hot_lines))

        recent_keywords = self.history_store.get_recent_keywords(3)
        if recent_keywords:
            sections.append(("最近搜索", recent_keywords))

        recent_videos = [
            truncate_display(history_item.title, width - 4)
            for history_item in self.history_store.get_recent_videos(3)
            if (history_item.bvid or history_item.aid) != (item.bvid or item.aid)
        ]
        if recent_videos:
            sections.append(("最近浏览", recent_videos[:3]))

        sections.append(("快捷操作", ["Enter 查看详情", "a 播放/暂停音频", "x 停止音频", "f 收藏当前视频", "m 打开收藏夹"]))

        footer_y = y + height - 2
        available_body_lines = max(0, footer_y - content_y)
        body_cursor = content_y
        for title, lines in sections:
            if available_body_lines <= 0:
                break
            stdscr.addnstr(body_cursor, x + 2, title, width - 4, self.attr_accent())
            body_cursor += 1
            available_body_lines -= 1
            if available_body_lines <= 0:
                break
            for line in lines:
                if available_body_lines <= 0:
                    break
                stdscr.addnstr(body_cursor, x + 2, truncate_display(line, width - 4), width - 4)
                body_cursor += 1
                available_body_lines -= 1
        stdscr.addnstr(y + height - 2, x + 2, "Enter 查看详情", width - 4, self.attr_muted())

    def draw_grid_card(self, stdscr: Any, y: int, x: int, height: int, width: int, index: int, item: VideoItem, selected: bool) -> None:
        label = f"{index + 1:02d}"
        self.draw_box(stdscr, y, x, height, width, label)
        title_attr = self.attr_selected() if selected else self.attr_title()
        title = f"★ {item.title}" if self.history_store.is_favorite(item) else item.title
        stdscr.addnstr(y + 1, x + 2, truncate_display(title, width - 4), width - 4, title_attr)
        stdscr.addnstr(y + 2, x + 2, truncate_display(item.author, width - 4), width - 4, self.attr_muted())
        if height >= 5:
            metrics = f"▶ {human_count(item.play)}  🕒 {item.duration}"
            stdscr.addnstr(y + 3, x + 2, truncate_display(metrics, width - 4), width - 4, self.attr_muted())
        if selected and height >= 5:
            stdscr.addnstr(y + height - 2, x + 2, "当前选中", width - 4, self.attr_accent())

    def draw_comments_panel(self, stdscr: Any, y: int, x: int, height: int, width: int) -> None:
        panel_label = "评论预览" if self.mode == "favorites" else "热评预览"
        self.draw_box(stdscr, y, x, height, width, panel_label)
        if height < 4:
            return
        comments = self.current_comments()
        comment_error = self.current_comment_error()
        if comment_error and not comments:
            lines = [
                *wrap_display(f"评论加载失败：{comment_error}", width=max(12, width - 4)),
                "按 o 在浏览器查看完整评论",
                "按 c 重试，按 r 刷新页面",
            ]
            for index, line in enumerate(lines[: height - 2], start=1):
                attr = self.attr_accent() if index == 1 else self.attr_muted()
                stdscr.addnstr(y + index, x + 2, truncate_display(line, width - 4), width - 4, attr)
            return
        if not comments:
            if self.current_comments_loaded():
                stdscr.addnstr(y + 1, x + 2, "当前视频暂无可显示热评", width - 4, self.attr_muted())
                stdscr.addnstr(y + 2, x + 2, "按 r 刷新页面，按 o 浏览器查看", width - 4, self.attr_muted())
            else:
                stdscr.addnstr(y + 1, x + 2, "按 c 加载当前视频评论", width - 4, self.attr_muted())
                stdscr.addnstr(y + 2, x + 2, "r 刷新当前视图", width - 4, self.attr_muted())
            return

        cursor = y + 1
        available = height - 2
        for index, comment in enumerate(comments, start=1):
            if available <= 0:
                break
            header = truncate_display(
                f"{index}. {comment.author} · {human_count(comment.like)} 赞 · {format_timestamp(comment.ctime)}",
                width - 4,
            )
            stdscr.addnstr(cursor, x + 2, header, width - 4, self.attr_accent() if index == 1 else self.attr_muted())
            cursor += 1
            available -= 1
            if available <= 0:
                break
            for line in wrap_display(comment.message or "暂无评论内容", width=max(12, width - 4)):
                if available <= 0:
                    break
                stdscr.addnstr(cursor, x + 2, line, width - 4)
                cursor += 1
                available -= 1
            if available <= 0:
                break
            stdscr.addnstr(cursor, x + 2, "", width - 4)
            cursor += 1
            available -= 1

    def mode_token(self) -> str:
        if self.detail_mode:
            return "详情"
        if self.mode == "search":
            return "搜索"
        if self.mode == "history":
            return "历史"
        if self.mode == "favorites":
            return "收藏夹"
        return self.active_channel()["label"]

    def draw_detail_summary(self, stdscr: Any, start_y: int, start_x: int, width: int, height: int) -> None:
        item = self.current_detail_item()
        if item is None:
            stdscr.addnstr(start_y, start_x, "当前没有选中的视频", width, self.attr_muted())
            return

        title = f"★ {item.title}" if self.history_store.is_favorite(item) else item.title
        summary_lines = [
            title,
            f"UP主 {item.author}",
            f"播放 {human_count(item.play)}   弹幕 {human_count(item.danmaku)}   时长 {item.duration}",
            f"发布时间 {format_timestamp(item.pubdate)}",
            f"编号 {item.bvid or item.aid}",
            "",
            "链接",
            truncate_display(item.url, width=width),
            "",
            "简介",
        ]
        desc_lines = wrap_display(item.description or "暂无简介", width=max(20, width))
        lines = summary_lines + desc_lines
        for offset, line in enumerate(lines[:height]):
            if offset == 0:
                attr = self.attr_title()
            elif offset in (1, 2, 3, 4):
                attr = self.attr_muted()
            elif line in ("链接", "简介"):
                attr = self.attr_accent()
            else:
                attr = 0
            stdscr.addnstr(start_y + offset, start_x, line, width, attr)

    def draw_favorites_list(self, stdscr: Any, y: int, x: int, height: int, width: int) -> None:
        label = f"收藏列表 · {len(self.items)} 条"
        self.draw_box(stdscr, y, x, height, width, label)
        if height < 4:
            return
        if not self.items:
            stdscr.addnstr(y + 2, x + 2, "收藏夹还是空的", width - 4, self.attr_muted())
            if height >= 6:
                stdscr.addnstr(y + 3, x + 2, "看到喜欢的视频时按 f 就能加入收藏。", width - 4, self.attr_muted())
            return

        cursor = y + 1
        for index, item in enumerate(self.items):
            remaining = y + height - cursor - 1
            if remaining < 2:
                break
            selected = index == self.selected_index
            prefix = "›" if selected else " "
            title = f"{prefix} {index + 1}. "
            title += f"★ {item.title}" if self.history_store.is_favorite(item) else item.title
            title_attr = self.attr_selected() if selected else self.attr_title()
            stdscr.addnstr(cursor, x + 2, truncate_display(title, width - 4), width - 4, title_attr)
            cursor += 1

            meta = f"{item.author} · {human_count(item.play)} 播放 · {item.duration}"
            stdscr.addnstr(cursor, x + 2, truncate_display(meta, width - 4), width - 4, self.attr_muted())
            cursor += 1

            if remaining >= 4:
                ref_line = f"{item.bvid or item.aid} · {format_timestamp(item.pubdate)}"
                stdscr.addnstr(cursor, x + 2, truncate_display(ref_line, width - 4), width - 4, self.attr_muted())
                cursor += 1

            if cursor < y + height - 1:
                stdscr.addnstr(cursor, x + 2, "·" * max(1, min(width - 4, 12)), width - 4, self.attr_muted())
                cursor += 1

    def draw_favorites_view(self, stdscr: Any, height: int, width: int) -> None:
        header = " 我的收藏 "
        header_right = f"共 {len(self.items)} 条"
        stdscr.addnstr(0, 0, header, width - 1, self.attr_header())
        right_x = max(0, width - display_width(header_right) - 1)
        stdscr.addnstr(0, right_x, header_right, width - right_x - 1, self.attr_header())

        selected = self.selected_item
        if selected is None:
            subtitle = "本地收藏，稍后可用 o 在浏览器继续看"
        else:
            subtitle = truncate_display(
                f"当前选中 · {selected.author} · {human_count(selected.play)} 播放 · a 播放/暂停音频 · x 停止 · o 浏览器打开",
                max(20, width - 2),
            )
        stdscr.addnstr(1, 0, subtitle, width - 1, self.attr_muted())

        content_top = 3
        content_height = height - content_top - 3
        left_width = max(34, width * 36 // 100)
        left_width = min(left_width, width - 40)
        right_x = left_width + 1
        right_width = width - right_x

        self.draw_favorites_list(stdscr, content_top, 0, content_height, left_width)

        preview_height = content_height
        comments_height = 0
        if content_height >= 16:
            preview_height = max(9, content_height * 55 // 100)
            comments_height = content_height - preview_height
            if comments_height < 5:
                preview_height = content_height
                comments_height = 0

        self.draw_box(stdscr, content_top, right_x, preview_height, right_width, "视频预览")
        self.draw_detail_summary(stdscr, content_top + 1, right_x + 2, max(12, right_width - 4), max(1, preview_height - 2))

        if comments_height >= 5:
            self.draw_comments_panel(stdscr, content_top + preview_height, right_x, comments_height, right_width)

    def draw_split_view(self, stdscr: Any, height: int, width: int) -> None:
        import curses

        header = " 哔哩哔哩终端首页 "
        header_right = f"{self.mode_token()} · 第 {self.page} 页"
        stdscr.addnstr(0, 0, header, width - 1, self.attr_header())
        right_x = max(0, width - display_width(header_right) - 1)
        stdscr.addnstr(0, right_x, header_right, width - right_x - 1, self.attr_header())
        stdscr.addnstr(1, 0, " " * max(1, width - 1), width - 1, self.attr_muted())
        tabs = [
            ("首页流", "hot"),
            ("搜索", "search"),
            ("历史记录", "history"),
            ("收藏夹", "favorites"),
        ]
        tab_x = 0
        for label, mode in tabs:
            chip = f"[{label}]"
            chip_width = display_width(chip)
            if tab_x + chip_width >= width - 1:
                break
            attr = self.attr_accent() if self.mode == mode else self.attr_muted()
            stdscr.addnstr(1, tab_x, chip, chip_width, attr)
            tab_x += chip_width + 2
        if self.mode == "search" and self.keyword:
            search_hint = f"当前搜索：{truncate_display(self.keyword, max(10, width // 4))}"
        elif self.mode == "history":
            search_hint = "按 v 查看最近浏览"
        elif self.mode == "favorites":
            search_hint = "按 a 播放/暂停音频，x 停止，o 打开"
        else:
            search_hint = "Tab 切换分区，1-9 直选，/ 搜索"
        hint_x = max(0, width - display_width(search_hint) - 1)
        stdscr.addnstr(1, hint_x, search_hint, width - hint_x - 1, self.attr_muted())

        stdscr.hline(2, 0, curses.ACS_HLINE, width)

        banner_height = self.draw_banner(stdscr, 3, width)
        chips_height = self.draw_category_row(stdscr, 3 + banner_height, width)

        content_top = 3 + banner_height + chips_height + 1
        content_height = height - content_top - 3
        left_width = max(34, width * 40 // 100)
        left_width = min(left_width, width - 28)
        right_x = left_width + 1
        right_width = width - right_x

        featured_item = self.items[0] if self.items else None
        self.draw_featured_card(stdscr, content_top, 0, content_height, left_width, featured_item, self.selected_index == 0)

        grid_items = self.items[1:]
        grid_cols = 2
        gap = 1
        card_width = max(18, (right_width - (grid_cols - 1) * gap) // grid_cols)
        card_height = 5
        max_grid_rows = max(1, min(2, (len(grid_items) + grid_cols - 1) // grid_cols))
        grid_height = min(content_height, max_grid_rows * card_height)
        visible_grid_items = grid_items[: max_grid_rows * grid_cols]

        for offset, item in enumerate(visible_grid_items):
            row = offset // grid_cols
            col = offset % grid_cols
            card_x = right_x + col * (card_width + gap)
            card_y = content_top + row * card_height
            if card_y + card_height > content_top + grid_height:
                break
            item_index = offset + 1
            self.draw_grid_card(
                stdscr,
                card_y,
                card_x,
                card_height,
                card_width,
                item_index,
                item,
                self.selected_index == item_index,
            )

        comments_y = content_top + grid_height
        comments_height = content_height - grid_height
        if comments_height >= 5:
            self.draw_comments_panel(stdscr, comments_y, right_x, comments_height, right_width)

    def draw_detail_view(self, stdscr: Any, height: int, width: int) -> None:
        import curses

        header = " 详情页 "
        header_right = "j/k 滚动  a 播放/暂停  x 停止  f 收藏  o 浏览器打开  c 刷新评论  Esc 返回  ? 帮助"
        stdscr.addnstr(0, 0, header, width - 1, self.attr_header())
        right_x = max(0, width - display_width(header_right) - 1)
        stdscr.addnstr(0, right_x, header_right, width - right_x - 1, self.attr_header())
        stdscr.hline(1, 0, curses.ACS_HLINE, width)
        item = self.current_detail_item()
        title = item.title if item else "没有结果"
        if item and self.history_store.is_favorite(item):
            title = f"★ {title}"
        content_top = 2
        content_height = height - 5
        self.draw_box(stdscr, content_top, 0, content_height, width, "视频详情")
        stdscr.addnstr(content_top + 1, 2, truncate_display(title, width - 4), width - 4, self.attr_title())
        detail_lines = self.get_detail_lines(max(20, width - 4))
        self.clamp_detail_scroll(width - 4, content_height - 4)
        visible_lines = detail_lines[self.detail_scroll : self.detail_scroll + content_height - 4]
        for offset, line in enumerate(visible_lines):
            attr = self.attr_accent() if "简介:" in line else (self.attr_muted() if ":" in line and offset < 10 else 0)
            stdscr.addnstr(content_top + 2 + offset, 2, line, width - 4, attr)
        footer = f"滚动 {self.detail_scroll + 1}-{self.detail_scroll + len(visible_lines)} / {len(detail_lines)}"
        stdscr.addnstr(content_top + content_height - 2, 2, footer, width - 4, self.attr_muted())

    def draw(self, stdscr: Any) -> None:
        import curses

        stdscr.erase()
        height, width = stdscr.getmaxyx()
        if height < 12 or width < 70:
            stdscr.addnstr(0, 0, "终端太小，至少需要 70x12。", max(1, width - 1))
            stdscr.refresh()
            return

        if self.detail_mode:
            self.draw_detail_view(stdscr, height, width)
        elif self.mode == "favorites":
            self.draw_favorites_view(stdscr, height, width)
        else:
            self.draw_split_view(stdscr, height, width)

        stdscr.hline(height - 2, 0, curses.ACS_HLINE, width)
        if self.mode == "favorites":
            shortcuts = "j/k 移动  Enter 详情  a 播放/暂停  x 停止  f 取消收藏  o 浏览器打开  c 评论  b 返回  q 退出"
        else:
            shortcuts = "Tab 分区  1-9 直选  / 搜索  a 播放/暂停  x 停止  f 收藏  m 收藏夹  c 评论  Enter 详情  q 退出"
        stdscr.addnstr(height - 2, 2, shortcuts, width - 4, self.attr_muted())
        stdscr.addnstr(height - 1, 0, f"状态: {self.status}", width - 1, self.attr_accent())
        if self.show_help:
            self.draw_help_overlay(stdscr, height, width)
        stdscr.refresh()

    def run(self, stdscr: Any) -> None:
        import curses

        self.init_theme()
        curses.curs_set(0)
        stdscr.keypad(True)
        self.load_items()
        while True:
            self.draw(stdscr)
            key = stdscr.getch()
            try:
                if self.show_help:
                    if key in (ord("?"), ord("q"), 27, 10, 13):
                        self.show_help = False
                    continue

                if self.detail_mode:
                    if key in (ord("?"),):
                        self.show_help = True
                    elif key in (27, curses.KEY_LEFT, ord("b")):
                        self.detail_mode = False
                        self.detail_scroll = 0
                        self.status = "已返回列表"
                    elif key in (curses.KEY_UP, ord("k")):
                        self.detail_scroll = max(0, self.detail_scroll - 1)
                    elif key in (curses.KEY_DOWN, ord("j")):
                        self.detail_scroll += 1
                    elif key == curses.KEY_PPAGE:
                        self.detail_scroll = max(0, self.detail_scroll - 10)
                    elif key == curses.KEY_NPAGE:
                        self.detail_scroll += 10
                    elif key == ord("o"):
                        self.open_selected()
                    elif key == ord("a"):
                        self.play_selected_audio()
                    elif key == ord("x"):
                        self.stop_audio()
                    elif key == ord("f"):
                        self.toggle_selected_favorite()
                    elif key == ord("c"):
                        self.refresh_comments()
                    elif key == ord("r"):
                        self.refresh_comments()
                    elif key in (ord("q"), 3):
                        return
                    continue

                if key in (ord("q"), 3):
                    return
                if key in (ord("?"),):
                    self.show_help = True
                elif key in (curses.KEY_UP, ord("k")):
                    if self.items:
                        self.selected_index = max(0, self.selected_index - 1)
                elif key in (curses.KEY_DOWN, ord("j")):
                    if self.items:
                        self.selected_index = min(len(self.items) - 1, self.selected_index + 1)
                elif key == ord("b"):
                    self.restore_previous_state()
                elif key in (9,):
                    self.cycle_channel(1)
                elif key == curses.KEY_BTAB:
                    self.cycle_channel(-1)
                elif ord("1") <= key <= ord("9"):
                    self.set_channel(key - ord("1"))
                elif key in (ord("g"),):
                    self.selected_index = 0
                elif key in (ord("G"),):
                    self.selected_index = max(0, len(self.items) - 1)
                elif key in (10, 13, curses.KEY_RIGHT):
                    self.load_selected_detail(enter_detail_mode=True)
                elif key == ord("o"):
                    self.open_selected()
                elif key == ord("a"):
                    self.play_selected_audio()
                elif key == ord("x"):
                    self.stop_audio()
                elif key == ord("r"):
                    self.refresh_current_view()
                elif key == ord("c"):
                    self.refresh_comments()
                elif key == ord("h"):
                    self.switch_mode("hot")
                elif key == ord("v"):
                    self.switch_mode("history")
                elif key == ord("m"):
                    self.switch_mode("favorites")
                elif key == ord("f"):
                    self.toggle_selected_favorite()
                elif key == ord("l"):
                    self.rerun_last_search()
                elif key == ord("d"):
                    keyword = self.default_search_keyword or self.client.search_default()
                    if keyword:
                        self.history_store.add_keyword(keyword)
                        self.switch_mode("search", keyword=keyword)
                    else:
                        self.status = "当前没有默认搜索词"
                elif key in (ord("/"), ord("s")):
                    keyword = self.prompt_input(stdscr, "搜索关键词: ", self.keyword if self.mode == "search" else "")
                    if keyword:
                        self.history_store.add_keyword(keyword)
                        self.switch_mode("search", keyword=keyword)
                    else:
                        self.status = "已取消搜索"
                elif key in (ord("n"), curses.KEY_NPAGE):
                    if self.mode in {"history", "favorites"}:
                        self.status = "当前列表没有分页"
                    else:
                        self.push_list_state()
                        self.page += 1
                        self.selected_index = 0
                        self.load_items()
                elif key in (ord("p"), curses.KEY_PPAGE):
                    if self.mode in {"history", "favorites"}:
                        self.status = "当前列表没有分页"
                    elif self.page > 1:
                        self.push_list_state()
                        self.page -= 1
                        self.selected_index = 0
                        self.load_items()
                    else:
                        self.status = "已经是第一页"
            except (BilibiliAPIError, ValueError) as exc:
                self.status = f"错误: {exc}"


def run_tui(client: BilibiliClient, history_store: HistoryStore) -> int:
    import curses

    def _main(stdscr: Any) -> None:
        BilibiliTUI(client, history_store).run(stdscr)

    curses.wrapper(_main)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="把 Bilibili 常用浏览操作搬到终端里。")
    subparsers = parser.add_subparsers(dest="command")

    hot_parser = subparsers.add_parser("hot", help="查看热门视频")
    hot_parser.add_argument("-p", "--page", type=int, default=1, help="页码")
    hot_parser.add_argument("-n", "--limit", type=int, default=10, help="数量")

    search_parser = subparsers.add_parser("search", help="搜索视频")
    search_parser.add_argument("keyword", help="关键词")
    search_parser.add_argument("-p", "--page", type=int, default=1, help="页码")
    search_parser.add_argument("-n", "--limit", type=int, default=10, help="数量")

    comments_parser = subparsers.add_parser("comments", help="查看视频热评")
    comments_parser.add_argument("ref", help="BV号 / av号 / URL")
    comments_parser.add_argument("-n", "--limit", type=int, default=5, help="数量")

    recommend_parser = subparsers.add_parser("recommend", help="查看首页推荐流")
    recommend_parser.add_argument("-p", "--page", type=int, default=1, help="页码")
    recommend_parser.add_argument("-n", "--limit", type=int, default=10, help="数量")

    add_rank_arguments(subparsers.add_parser("rank", help="查看分区排行榜"))
    add_rank_arguments(subparsers.add_parser("ranking", help="rank 的别名"))

    add_bangumi_arguments(subparsers.add_parser("bangumi", help="查看番剧 / 国创 / 影视更新或索引"))

    precious_parser = subparsers.add_parser("precious", help="查看入站必刷")
    precious_parser.add_argument("-p", "--page", type=int, default=1, help="页码")
    precious_parser.add_argument("-n", "--limit", type=int, default=10, help="数量")

    trending_parser = subparsers.add_parser("trending", help="查看首页热搜词")
    trending_parser.add_argument("-n", "--limit", type=int, default=10, help="数量")

    video_parser = subparsers.add_parser("video", help="查看视频详情")
    video_parser.add_argument("ref", help="BV号 / av号 / URL")

    open_parser = subparsers.add_parser("open", help="浏览器打开视频")
    open_parser.add_argument("ref", help="BV号 / av号 / URL")

    audio_parser = subparsers.add_parser("audio", help="播放或控制视频音频")
    audio_parser.add_argument("ref", help="BV号 / av号 / URL / pause / resume / toggle / stop")

    favorite_parser = subparsers.add_parser("favorite", help="将视频加入收藏夹")
    favorite_parser.add_argument("ref", help="BV号 / av号 / URL")

    favorites_parser = subparsers.add_parser("favorites", help="查看或操作收藏夹")
    favorites_subparsers = favorites_parser.add_subparsers(dest="favorites_action")
    favorites_open_parser = favorites_subparsers.add_parser("open", help="浏览器打开收藏夹中的视频")
    favorites_open_parser.add_argument("ref", help="收藏夹序号 / BV号 / av号 / URL")
    favorites_remove_parser = favorites_subparsers.add_parser("remove", help="从收藏夹移除视频")
    favorites_remove_parser.add_argument("ref", help="收藏夹序号 / BV号 / av号 / URL")

    subparsers.add_parser("history", help="查看最近搜索和最近浏览")
    subparsers.add_parser("repl", help="进入交互模式")
    subparsers.add_parser("tui", help="进入全屏终端界面")

    audio_worker_parser = subparsers.add_parser("audio-worker", help=argparse.SUPPRESS)
    audio_worker_parser.add_argument("--url", required=True, help=argparse.SUPPRESS)
    audio_worker_parser.add_argument("--referer", required=True, help=argparse.SUPPRESS)
    audio_worker_parser.add_argument("--user-agent", required=True, help=argparse.SUPPRESS)
    audio_worker_parser.add_argument("--title", default="", help=argparse.SUPPRESS)
    return parser


def run_once(args: argparse.Namespace, client: BilibiliClient, history_store: HistoryStore) -> int:
    if args.command == "hot":
        print_video_list(client.popular(page=args.page, page_size=args.limit), f"热门视频 第 {args.page} 页")
        return 0
    if args.command == "recommend":
        print_video_list(client.recommend(page=args.page, page_size=args.limit), f"首页推荐 第 {args.page} 页")
        return 0
    if args.command in {"rank", "ranking"}:
        rid, label = resolve_region_rid(getattr(args, "region", None), getattr(args, "rid", None))
        print_video_list(
            client.region_ranking(rid=rid, day=args.day, page=args.page, page_size=args.limit),
            f"{label} 排行榜 | 第 {args.page} 页",
        )
        return 0
    if args.command == "bangumi":
        meta = resolve_bangumi_category(args.category)
        print_video_list(
            client.bangumi(
                category=str(meta["label"]),
                index=args.index,
                area=args.area,
                page=args.page,
                page_size=args.limit,
            ),
            build_bangumi_title(str(meta["label"]), index=args.index, page=args.page, area=args.area),
        )
        return 0
    if args.command == "precious":
        print_video_list(client.precious(page=args.page, page_size=args.limit), f"入站必刷 第 {args.page} 页")
        return 0
    if args.command == "search":
        items = client.search(keyword=args.keyword, page=args.page, page_size=args.limit)
        history_store.add_keyword(args.keyword)
        print_video_list(items, f"搜索结果: {args.keyword} | 第 {args.page} 页")
        return 0
    if args.command == "comments":
        item = client.video(args.ref)
        if item.aid is None:
            raise ValueError("当前视频缺少 AID，无法加载评论")
        print_comments(item, client.comments(item.aid, args.limit, bvid=item.bvid))
        return 0
    if args.command == "trending":
        print("\n首页热搜")
        print("========")
        for index, keyword in enumerate(client.trending_keywords(args.limit), start=1):
            print(f"{index:>2}. {keyword}")
        return 0
    if args.command == "video":
        item = client.video(args.ref)
        history_store.add_video(item)
        print_video_detail(item)
        return 0
    if args.command == "open":
        url = open_video_target(args.ref)
        print(f"已打开: {url}")
        return 0
    if args.command == "audio":
        action = args.ref.lower()
        if action == "pause":
            print(pause_audio_playback())
            return 0
        if action == "resume":
            print(resume_audio_playback())
            return 0
        if action == "toggle":
            print(toggle_audio_playback())
            return 0
        if action == "stop":
            print(stop_audio_playback())
            return 0
        item = client.video(args.ref)
        history_store.add_video(item)
        print(play_audio_for_item(client, item))
        return 0
    if args.command == "favorite":
        item = client.video(args.ref)
        added = history_store.add_favorite(item)
        print(f"{'已收藏' if added else '收藏夹已更新'}: {item.title}")
        return 0
    if args.command == "favorites":
        action = getattr(args, "favorites_action", None)
        if action is None:
            print_favorites(history_store)
            return 0
        shell = BilibiliCLI(client, history_store)
        if action == "open":
            item = shell._resolve_favorite_item(args.ref)
            webbrowser.open(item.url)
            history_store.add_video(item)
            print(f"已打开收藏: {item.url}")
            return 0
        if action == "remove":
            item = shell._resolve_favorite_item(args.ref)
            history_store.remove_favorite(item)
            print(f"已移出收藏: {item.title}")
            return 0
    if args.command == "history":
        print_history(history_store)
        return 0
    if args.command == "tui":
        return run_tui(client, history_store)
    if args.command == "audio-worker":
        return run_audio_worker(args.url, args.referer, args.user_agent, args.title)
    BilibiliCLI(client, history_store).cmdloop()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    client = BilibiliClient()
    history_store = HistoryStore()
    try:
        return run_once(args, client, history_store)
    except (BilibiliAPIError, ValueError) as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
