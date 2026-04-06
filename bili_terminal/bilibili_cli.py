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
import sys
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
DEFAULT_HISTORY_PATH = ".omx/state/bilibili-cli-history.json"
MAX_HISTORY_ITEMS = 40
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
]

BVID_PATTERN = re.compile(r"(BV[0-9A-Za-z]{10})")
AID_PATTERN = re.compile(r"\bav(\d+)\b", re.IGNORECASE)
HTML_TAG_PATTERN = re.compile(r"<[^>]+>")
WHITESPACE_PATTERN = re.compile(r"\s+")
COMMON_MOJIBAKE_CHARS = set("ÃÂÐÑãäåæçèéêëìíîïðñòóôõöùúûüýþÿ")
INITIAL_STATE_PATTERN = re.compile(r"window\.__INITIAL_STATE__=(\{.*?\});\(function", re.S)
INITIAL_STATE_FALLBACK_PATTERN = re.compile(r"window\.__INITIAL_STATE__=(\{.*?\})\s*var\s+isBilibili", re.S)
COMMENT_WBI_KEYS_PATTERN = re.compile(r'encWbiKeys:\{wbiImgKey:"([^"]+)",wbiSubKey:"([^"]+)"\}')
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
    bvid = payload.get("bvid")
    if bvid:
        return f"https://www.bilibili.com/video/{bvid}"
    aid = payload.get("aid")
    if aid:
        return f"https://www.bilibili.com/video/av{aid}"
    return "https://www.bilibili.com/"


def build_watch_url(ref_type: str, value: str) -> str:
    return f"https://www.bilibili.com/video/{value}" if ref_type == "bvid" else f"https://www.bilibili.com/video/av{value}"


def open_video_target(target: str) -> str:
    ref_type, value = parse_video_ref(target)
    url = build_watch_url(ref_type, value)
    webbrowser.open(url)
    return url


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
        play=int(payload.get("play") or stat.get("view") or 0),
        danmaku=int(payload.get("video_review") or payload.get("danmaku") or stat.get("danmaku") or 0),
        like=int(payload.get("like") or stat.get("like") or 0),
        favorite=int(payload.get("favorites") or stat.get("favorite") or 0),
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


class HistoryStore:
    def __init__(self, path: str = DEFAULT_HISTORY_PATH, max_items: int = MAX_HISTORY_ITEMS) -> None:
        self.path = path
        self.max_items = max_items
        self._data: dict[str, list[Any]] = {
            "recent_keywords": [],
            "recent_videos": [],
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
        key = payload.get("bvid") or payload.get("aid") or payload.get("url")
        videos = [video for video in self._data["recent_videos"] if (video.get("bvid") or video.get("aid") or video.get("url")) != key]
        videos.insert(0, payload)
        self._data["recent_videos"] = videos[: self.max_items]
        self.save()

    def get_recent_keywords(self, limit: int = 10) -> list[str]:
        return list(self._data["recent_keywords"][:limit])

    def get_recent_videos(self, limit: int = 20) -> list[VideoItem]:
        return [item_from_payload(payload) for payload in self._data["recent_videos"][:limit]]


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
        "video <BV号|av号|URL|序号>, open <序号|BV号|URL>, exit"
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

    def do_video(self, arg: str) -> None:
        if not arg.strip():
            print("用法: video <BV号|av号|URL|序号>")
            return
        target = self._resolve_target(arg.strip())
        item = self.client.video(target)
        self.history_store.add_video(item)
        print_video_detail(item)

    def do_history(self, _: str) -> None:
        print_history(self.history_store)

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
        print(f"    {item.bvid or item.aid} | {item.url}")
    print("\n提示: 可用 `video 1` 查看详情，或 `open 1` 在浏览器中打开。")


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
        f"UP主: {item.author}",
        f"BV号: {item.bvid or '-'}",
        f"AID: {item.aid or '-'}",
        f"时长: {item.duration}",
        f"发布时间: {format_timestamp(item.pubdate)}",
        f"播放: {human_count(item.play)}",
        f"弹幕: {human_count(item.danmaku)}",
        f"点赞: {human_count(item.like)}",
        f"收藏: {human_count(item.favorite)}",
        f"链接: {item.url}",
        "",
        "简介:",
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
        curses.init_pair(1, curses.COLOR_BLACK, curses.COLOR_CYAN)
        curses.init_pair(2, curses.COLOR_CYAN, -1)
        curses.init_pair(3, curses.COLOR_WHITE, -1)
        curses.init_pair(4, curses.COLOR_BLACK, curses.COLOR_WHITE)
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
        return f"{self.active_channel()['label']}  第 {self.page} 页"

    def active_channel(self) -> dict[str, Any]:
        return self.channels[self.channel_index]

    def _cache_key(self, item: VideoItem | None) -> str | None:
        if item is None:
            return None
        return item.bvid or str(item.aid)

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
            lines.extend(["", "热评:"])
            for index, comment in enumerate(comments, start=1):
                header = f"{index}. {comment.author} · {human_count(comment.like)} 赞 · {format_timestamp(comment.ctime)}"
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
        self.detail_cache[key] = self.client.video(key)
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

        win = stdscr.derwin(height, width, y, x)
        win.box()
        if label:
            win.addnstr(0, 2, f" {label} ", width - 4, self.attr_accent())

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
        channel_label = self.active_channel()["label"] if self.mode == "hot" else "搜索"
        section_line = f"当前分区 · {channel_label}"
        stdscr.addnstr(y + 3, centered_x(width, section_line, 2), section_line, width - 4, self.attr_muted())
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

        if height < 9:
            stdscr.addnstr(y + 1, x + 2, truncate_display(item.title, width - 4), width - 4, self.attr_title())
            stdscr.addnstr(y + 2, x + 2, truncate_display(item.author, width - 4), width - 4, self.attr_muted())
            stdscr.addnstr(y + height - 2, x + 2, "Enter 查看详情", width - 4, self.attr_muted())
            return

        title_attr = self.attr_selected() if selected else self.attr_title()
        title_lines = wrap_display(item.title, max(12, width - 4))
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

        sections.append(("快捷操作", ["Enter 查看详情", "/ 直接搜索", "Tab 切分区"]))

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
        stdscr.addnstr(y + 1, x + 2, truncate_display(item.title, width - 4), width - 4, title_attr)
        stdscr.addnstr(y + 2, x + 2, truncate_display(item.author, width - 4), width - 4, self.attr_muted())
        if height >= 5:
            metrics = f"{human_count(item.play)} 播放  {item.duration}"
            stdscr.addnstr(y + 3, x + 2, truncate_display(metrics, width - 4), width - 4, self.attr_muted())
        if selected and height >= 5:
            stdscr.addnstr(y + height - 2, x + 2, "当前选中", width - 4, self.attr_accent())

    def draw_comments_panel(self, stdscr: Any, y: int, x: int, height: int, width: int) -> None:
        self.draw_box(stdscr, y, x, height, width, "热评预览")
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
                stdscr.addnstr(y + 2, x + 2, "r 刷新整个首页内容", width - 4, self.attr_muted())
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
        return self.active_channel()["label"]

    def draw_detail_summary(self, stdscr: Any, start_y: int, start_x: int, width: int, height: int) -> None:
        item = self.current_detail_item()
        if item is None:
            stdscr.addnstr(start_y, start_x, "No item selected.", width, self.attr_muted())
            return

        summary_lines = [
            item.title,
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

    def draw_split_view(self, stdscr: Any, height: int, width: int) -> None:
        import curses

        header = " 哔哩哔哩终端首页 "
        header_right = f"{self.mode_token()} · 第 {self.page} 页"
        stdscr.addnstr(0, 0, header, width - 1, self.attr_header())
        right_x = max(0, width - display_width(header_right) - 1)
        stdscr.addnstr(0, right_x, header_right, width - right_x - 1, self.attr_header())
        mode_line = "[首页流]  [搜索]  [历史记录]"
        stdscr.addnstr(1, 0, mode_line, width - 1, self.attr_muted())
        active_marker_map = {
            "hot": "[首页流]",
            "search": "[搜索]",
            "history": "[历史记录]",
        }
        active_marker = active_marker_map.get(self.mode, "[首页流]")
        marker_x = mode_line.find(active_marker)
        if marker_x >= 0:
            stdscr.addnstr(1, marker_x, active_marker, len(active_marker), self.attr_accent())
        if self.mode == "search" and self.keyword:
            search_hint = f"当前搜索：{truncate_display(self.keyword, max(10, width // 4))}"
        elif self.mode == "history":
            search_hint = "按 v 查看最近浏览"
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
        header_right = "j/k 滚动  o 浏览器打开  c 刷新评论  Esc 返回  ? 帮助"
        stdscr.addnstr(0, 0, header, width - 1, self.attr_header())
        right_x = max(0, width - display_width(header_right) - 1)
        stdscr.addnstr(0, right_x, header_right, width - right_x - 1, self.attr_header())
        stdscr.hline(1, 0, curses.ACS_HLINE, width)
        item = self.current_detail_item()
        title = item.title if item else "没有结果"
        content_top = 2
        content_height = height - 5
        self.draw_box(stdscr, content_top, 0, content_height, width, "视频详情")
        stdscr.addnstr(content_top + 1, 2, truncate_display(title, width - 4), width - 4, self.attr_title())
        detail_lines = self.get_detail_lines(max(20, width - 4))
        self.clamp_detail_scroll(width - 4, content_height - 4)
        visible_lines = detail_lines[self.detail_scroll : self.detail_scroll + content_height - 4]
        for offset, line in enumerate(visible_lines):
            attr = self.attr_accent() if line == "简介:" else (self.attr_muted() if ":" in line and offset < 10 else 0)
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
        else:
            self.draw_split_view(stdscr, height, width)

        stdscr.hline(height - 2, 0, curses.ACS_HLINE, width)
        shortcuts = "Tab 分区  1-9 直选  / 搜索  c 评论  r 刷新  Enter 详情  q 退出"
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
                elif key == ord("r"):
                    self.refresh_current_view()
                elif key == ord("c"):
                    self.refresh_comments()
                elif key == ord("h"):
                    self.switch_mode("hot")
                elif key == ord("v"):
                    self.switch_mode("history")
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
                    if self.mode == "history":
                        self.status = "历史页没有分页"
                    else:
                        self.push_list_state()
                        self.page += 1
                        self.selected_index = 0
                        self.load_items()
                elif key in (ord("p"), curses.KEY_PPAGE):
                    if self.mode == "history":
                        self.status = "历史页没有分页"
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

    precious_parser = subparsers.add_parser("precious", help="查看入站必刷")
    precious_parser.add_argument("-p", "--page", type=int, default=1, help="页码")
    precious_parser.add_argument("-n", "--limit", type=int, default=10, help="数量")

    trending_parser = subparsers.add_parser("trending", help="查看首页热搜词")
    trending_parser.add_argument("-n", "--limit", type=int, default=10, help="数量")

    video_parser = subparsers.add_parser("video", help="查看视频详情")
    video_parser.add_argument("ref", help="BV号 / av号 / URL")

    open_parser = subparsers.add_parser("open", help="浏览器打开视频")
    open_parser.add_argument("ref", help="BV号 / av号 / URL")

    subparsers.add_parser("history", help="查看最近搜索和最近浏览")
    subparsers.add_parser("repl", help="进入交互模式")
    subparsers.add_parser("tui", help="进入全屏终端界面")
    return parser


def run_once(args: argparse.Namespace, client: BilibiliClient, history_store: HistoryStore) -> int:
    if args.command == "hot":
        print_video_list(client.popular(page=args.page, page_size=args.limit), f"热门视频 第 {args.page} 页")
        return 0
    if args.command == "recommend":
        print_video_list(client.recommend(page=args.page, page_size=args.limit), f"首页推荐 第 {args.page} 页")
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
    if args.command == "history":
        print_history(history_store)
        return 0
    if args.command == "tui":
        return run_tui(client, history_store)
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
