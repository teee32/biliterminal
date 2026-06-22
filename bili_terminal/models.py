from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from .textutil import compact_whitespace, normalize_duration, strip_html


class BilibiliAPIError(RuntimeError):
    pass


BVID_PATTERN = re.compile(r"(BV[0-9A-Za-z]{10})")
AID_PATTERN = re.compile(r"\bav(\d+)\b", re.IGNORECASE)


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
    cookie_header: str = ""


@dataclass(slots=True)
class AudioPlaybackState:
    pid: int | None
    title: str
    video_key: str | None
    backend: str = "process"
    paused: bool = False
    control_pid: int | None = None
    media_path: str | None = None
    ipc_socket: str | None = None


@dataclass(slots=True)
class VideoStream:
    url: str
    referer: str
    user_agent: str
    width: int
    height: int
    frame_rate: str
    codec: str
    bandwidth: int
    source_kind: str  # "dash-video" | "durl"
    cookie_header: str = ""


@dataclass(slots=True)
class VideoPlaybackState:
    pid: int | None
    title: str
    video_key: str | None
    playing: bool = True
    target_cols: int = 80
    target_rows: int = 24
    target_fps: int = 10


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
    bvid = payload.get("bvid")
    if bvid:
        return f"https://www.bilibili.com/video/{bvid}"
    aid = payload.get("aid")
    if aid:
        return f"https://www.bilibili.com/video/av{aid}"
    return "https://www.bilibili.com/"


def build_watch_url(ref_type: str, value: str) -> str:
    return f"https://www.bilibili.com/video/{value}" if ref_type == "bvid" else f"https://www.bilibili.com/video/av{value}"


def _as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def item_from_payload(payload: dict[str, Any]) -> VideoItem:
    stat = payload.get("stat") or {}
    cnt_info = payload.get("cnt_info") or {}
    owner = payload.get("owner")
    upper = payload.get("upper")
    if isinstance(owner, dict):
        author = owner.get("name", "-")
    elif isinstance(owner, str) and owner.strip():
        author = owner.strip()
    elif isinstance(upper, dict):
        author = upper.get("name", "-")
    else:
        author = (
            payload.get("author")
            or payload.get("author_name")
            or payload.get("owner_name")
            or payload.get("up_name")
            or "-"
        )
    return VideoItem(
        title=strip_html(payload.get("title", "")),
        author=author,
        bvid=payload.get("bvid"),
        aid=payload.get("aid"),
        duration=normalize_duration(payload.get("duration")),
        play=_as_int(payload.get("play") or stat.get("view") or cnt_info.get("play")),
        danmaku=_as_int(
            payload.get("video_review")
            or payload.get("danmaku")
            or stat.get("danmaku")
            or cnt_info.get("danmaku")
        ),
        like=_as_int(payload.get("like") or stat.get("like")),
        favorite=_as_int(
            payload.get("favorites") or stat.get("favorite") or cnt_info.get("collect")
        ),
        pubdate=payload.get("pubdate"),
        description=compact_whitespace(payload.get("description") or payload.get("desc") or ""),
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
    # Bilibili 的 aid 从 1 开始，0 永远是脏数据；用真值判断一并挡掉 None/0/空串
    aid = payload.get("aid")
    if aid:
        return f"av{aid}"
    url = payload.get("url")
    return str(url) if url else None


def video_key_from_item(item: VideoItem | None) -> str | None:
    if item is None:
        return None
    if item.bvid:
        return str(item.bvid)
    # aid=0 视为无效，避免脏数据生成 "av0" 污染去重集合
    if item.aid:
        return f"av{item.aid}"
    return str(item.url) if item.url else None


def video_key_from_ref(ref_type: str, value: str) -> str:
    return value if ref_type == "bvid" else f"av{value}"


# Bilibili 正片 / 音频流的可信主机后缀。媒体流地址是从远端 HTML 里正则抓取的
# __playinfo__.baseUrl，必须先校验再附带会话 Cookie，避免凭证被发往任意主机
# （凭证外泄 / SSRF）。*.bilivideo.com / .cn 是 PCDN，缺了会导致播放中断。
_TRUSTED_MEDIA_HOST_SUFFIXES = (
    ".bilibili.com",
    ".hdslb.com",
    ".akamaized.net",
    ".bilivideo.com",
    ".bilivideo.cn",
)


def is_trusted_media_host(url: str | None) -> bool:
    """仅当 url 是 https 且主机命中可信后缀时返回 True。"""
    if not url:
        return False
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme != "https" or not parsed.hostname:
        return False
    host = parsed.hostname.lower()
    return any(
        host == suffix.lstrip(".") or host.endswith(suffix)
        for suffix in _TRUSTED_MEDIA_HOST_SUFFIXES
    )


def comments_from_payload(payload: list[dict[str, Any]]) -> list[CommentItem]:
    comments: list[CommentItem] = []
    for item in payload:
        member = item.get("member") or {}
        content = item.get("content") or {}
        comments.append(
            CommentItem(
                author=member.get("uname") or "-",
                message=compact_whitespace(content.get("message") or ""),
                like=_as_int(item.get("like")),
                ctime=item.get("ctime"),
            )
        )
    return comments


def comments_from_thread_payload(payload: dict[str, Any], limit: int) -> list[CommentItem]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    fallback_counter = 0
    for field in ("top_replies", "replies"):
        for item in payload.get(field) or []:
            rpid = item.get("rpid_str") or item.get("rpid")
            if rpid is None:
                # 无 rpid 时用递增计数器兜底，避免 len(merged) 撞 key 丢评论
                fallback_counter += 1
                key = f"_anon_{fallback_counter}"
            else:
                key = str(rpid)
            if key in seen:
                continue
            seen.add(key)
            merged.append(item)
            if len(merged) >= limit:
                return comments_from_payload(merged)
    return comments_from_payload(merged)
