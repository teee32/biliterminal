from __future__ import annotations

import gzip
import hashlib
import http.cookiejar
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from typing import Any

from .models import (
    AudioStream,
    BilibiliAPIError,
    CommentItem,
    VideoItem,
    build_watch_url,
    comments_from_thread_payload,
    item_from_payload,
    parse_video_ref,
)
from .textutil import compact_whitespace

DEFAULT_TIMEOUT = 15
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
)

INITIAL_STATE_PATTERN = re.compile(r"window\.__INITIAL_STATE__=(\{.*?\});\(function", re.S)
INITIAL_STATE_FALLBACK_PATTERN = re.compile(r"window\.__INITIAL_STATE__=(\{.*?\})\s*var\s+isBilibili", re.S)
COMMENT_WBI_KEYS_PATTERN = re.compile(r'encWbiKeys:\{wbiImgKey:"([^"]+)",wbiSubKey:"([^"]+)"\}')
PLAYINFO_PATTERN = re.compile(r"window\.__playinfo__=(\{.*?\})</script>", re.S)
WBI_KEY_SANITIZE_PATTERN = re.compile(r"[!'()*]")
COMMENT_WEB_LOCATION = 1315875
COMMENT_WBI_MIXIN_TABLE = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35,
    27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13,
    37, 48, 7, 16, 24, 55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4,
    22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36, 20, 34, 44, 52,
]

FULL_LIST_CACHE_TTL = 300.0


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


def extract_audio_stream(
    playinfo: dict[str, Any],
    *,
    referer: str,
    user_agent: str,
    title: str,
) -> AudioStream:
    data = playinfo.get("data") or {}
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


class BilibiliClient:
    def __init__(self, timeout: int = DEFAULT_TIMEOUT, user_agent: str = DEFAULT_USER_AGENT) -> None:
        self.timeout = timeout
        self.user_agent = user_agent
        self.cookie_jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cookie_jar))
        self.comment_wbi_keys: dict[str, tuple[str, str]] = {}
        self._full_list_cache: dict[tuple[str, int], tuple[float, list[VideoItem]]] = {}

    def _build_headers(self, referer: str, accept: str = "application/json, text/plain, */*") -> dict[str, str]:
        parsed_referer = urllib.parse.urlparse(referer)
        origin = f"{parsed_referer.scheme}://{parsed_referer.netloc}" if parsed_referer.scheme and parsed_referer.netloc else referer
        return {
            "User-Agent": self.user_agent,
            "Accept": accept,
            "Accept-Encoding": "gzip, deflate",
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
        request_url = f"{url}?{query}" if query else url
        for attempt in range(2):
            request = urllib.request.Request(request_url, headers=self._build_headers(referer))
            try:
                with self._open(request) as response:
                    body = decode_response_body(response.read(), response.headers.get("Content-Encoding"))
                payload = json.loads(body)
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

    def _cached_full_list(self, cache_key: tuple[str, int], fetch: Any) -> list[VideoItem]:
        cached = self._full_list_cache.get(cache_key)
        now = time.monotonic()
        if cached and now - cached[0] < FULL_LIST_CACHE_TTL:
            return cached[1]
        items: list[VideoItem] = fetch()
        self._full_list_cache[cache_key] = (now, items)
        return items

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
        # 接口总是返回完整列表（约 100 条），缓存后本地分页，翻页不再重复下载
        def fetch() -> list[VideoItem]:
            data = self._request_json(
                "https://api.bilibili.com/x/web-interface/popular/precious",
                {"page": 1, "page_size": 100},
                "https://www.bilibili.com/",
            )
            return [item_from_payload(item) for item in data.get("list", [])]

        items = self._cached_full_list(("precious", 0), fetch)
        start = max(0, (page - 1) * page_size)
        return items[start : start + page_size]

    def region_ranking(self, rid: int, day: int = 3, page: int = 1, page_size: int = 10) -> list[VideoItem]:
        def fetch() -> list[VideoItem]:
            data = self._request_json(
                "https://api.bilibili.com/x/web-interface/ranking/region",
                {"rid": rid, "day": day, "original": 0},
                "https://www.bilibili.com/",
            )
            return [item_from_payload(item) for item in data]

        items = self._cached_full_list(("region", rid, day), fetch)
        start = max(0, (page - 1) * page_size)
        return items[start : start + page_size]

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

    def audio_stream_for_item(self, item: VideoItem) -> AudioStream:
        detail_item = item
        if not detail_item.bvid:
            if detail_item.aid is None:
                raise BilibiliAPIError("当前视频缺少 BV 号，无法解析音频流")
            detail_item = self.video(str(detail_item.aid))
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
        keywords = []
        for item in trending:
            word = compact_whitespace(item.get("show_name") or item.get("keyword") or "")
            if word:
                keywords.append(word)
        return keywords

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
