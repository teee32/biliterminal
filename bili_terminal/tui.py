from __future__ import annotations

import queue
import threading
import webbrowser
from typing import Any, Callable

from . import audio
from .client import BilibiliClient
from .history import HistoryStore
from .models import BilibiliAPIError, CommentItem, ListState, VideoItem
from .output import build_detail_lines
from .textutil import (
    centered_x,
    display_width,
    format_timestamp,
    human_count,
    truncate_display,
    wrap_display,
)

BILIBILI_PINK_RGB = (984, 447, 600)
TICK_MS = 100
STATUS_TTL_TICKS = 120
COMMENT_DEBOUNCE_TICKS = 4
SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

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
        self._jobs: queue.SimpleQueue = queue.SimpleQueue()
        self._loading = 0
        self._generation = 0
        self._spinner_index = 0
        self._status_ttl = -1
        self._comment_delay = -1
        self._comment_inflight: set[str] = set()
        self._detail_lines_cache: tuple[Any, list[str]] | None = None
        self._dirty = True
        self._audio_state = None
        self._audio_poll = 0

    # ---------- async plumbing ----------

    def _submit(self, work: Callable[[], Any], apply: Callable[[Any], None], status: str | None = None) -> None:
        if status is not None:
            self.set_status(status, sticky=True)
        self._loading += 1
        self._dirty = True

        def runner() -> None:
            try:
                result = work()
            except Exception as exc:  # noqa: BLE001 — 线程内必须兜底，否则 _loading 计数泄漏
                self._jobs.put((apply, None, exc))
                return
            self._jobs.put((apply, result, None))

        threading.Thread(target=runner, daemon=True).start()

    def _drain_jobs(self) -> None:
        while True:
            try:
                apply, result, exc = self._jobs.get_nowait()
            except queue.Empty:
                return
            self._loading = max(0, self._loading - 1)
            self._dirty = True
            if exc is not None:
                self.set_status(f"错误: {exc}", sticky=True)
                continue
            apply(result)

    def set_status(self, message: str, *, sticky: bool = False) -> None:
        self.status = message
        self._status_ttl = -1 if sticky else STATUS_TTL_TICKS
        self._dirty = True

    def _tick(self) -> None:
        self._drain_jobs()
        if self._loading > 0:
            self._spinner_index = (self._spinner_index + 1) % len(SPINNER_FRAMES)
            self._dirty = True
        if self._status_ttl > 0:
            self._status_ttl -= 1
            if self._status_ttl == 0:
                self.status = ""
                self._dirty = True
        if self._comment_delay > 0:
            self._comment_delay -= 1
        elif self._comment_delay == 0:
            self._comment_delay = -1
            self._start_comment_load()
        # 每秒轮询一次播放状态，让顶栏的正在播放指示跟上外部变化
        self._audio_poll += 1
        if self._audio_poll >= 10:
            self._audio_poll = 0
            previous = (self._audio_state.title, self._audio_state.paused) if self._audio_state else None
            self._refresh_audio_state()
            current = (self._audio_state.title, self._audio_state.paused) if self._audio_state else None
            if previous != current:
                self._dirty = True

    def _schedule_comment_load(self, *, immediate: bool = False) -> None:
        self._comment_delay = 0 if immediate else COMMENT_DEBOUNCE_TICKS

    def _start_comment_load(self, *, force: bool = False, announce: bool = False) -> None:
        item = self.selected_item
        key = self._cache_key(item)
        if item is None or key is None or key in self._comment_inflight:
            return
        if not force and (key in self.comment_cache or key in self.comment_errors):
            return
        aid = item.aid
        referer_bvid = item.bvid
        cached_detail = self.detail_cache.get(key)
        if aid is None and cached_detail is not None and cached_detail.aid is not None:
            aid = cached_detail.aid
            referer_bvid = cached_detail.bvid or referer_bvid
        self._comment_inflight.add(key)

        def work() -> Any:
            local_aid = aid
            local_bvid = referer_bvid
            detail_item = None
            if local_aid is None:
                detail_item = self.client.video(key)
                local_aid = detail_item.aid
                local_bvid = detail_item.bvid or local_bvid
            if local_aid is None:
                raise BilibiliAPIError("当前视频缺少 AID，无法加载评论")
            return detail_item, self.client.comments(local_aid, page_size=4, bvid=local_bvid)

        def apply(result: Any) -> None:
            self._comment_inflight.discard(key)
            detail_item, comments = result
            if detail_item is not None:
                self.detail_cache[key] = detail_item
            self.comment_cache[key] = comments
            self.comment_loaded.add(key)
            self.comment_errors.pop(key, None)
            self._detail_lines_cache = None
            if announce:
                self.set_status(f"已加载评论 {len(comments)} 条")

        def runner() -> None:
            try:
                result = work()
            except Exception as exc:  # noqa: BLE001 — 线程内必须兜底，否则 _comment_inflight 泄漏
                def apply_error(_: Any) -> None:
                    self._comment_inflight.discard(key)
                    self.comment_cache[key] = []
                    self.comment_loaded.discard(key)
                    self.comment_errors[key] = str(exc)
                    self._detail_lines_cache = None
                    if announce:
                        self.set_status(f"评论加载失败: {exc}", sticky=True)
                self._jobs.put((apply_error, None, None))
                return
            self._jobs.put((apply, result, None))

        self._loading += 1
        self._dirty = True
        threading.Thread(target=runner, daemon=True).start()

    # ---------- theming ----------

    # 256 色终端下的 xterm 调色板索引；16 色终端退化到基础色
    PALETTE_256 = {
        "pink": 211,
        "text": 252,
        "bright": 231,
        "blue": 75,
        "gold": 215,
        "green": 114,
        "red": 203,
        "border": 238,
        "muted": 244,
    }

    def init_theme(self) -> None:
        import curses

        if not curses.has_colors():
            self.use_colors = False
            return
        curses.start_color()
        curses.use_default_colors()
        colors = getattr(curses, "COLORS", 8)

        if colors >= 256:
            p = self.PALETTE_256
            pink, text, bright = p["pink"], p["text"], p["bright"]
            blue, gold, green, red = p["blue"], p["gold"], p["green"], p["red"]
            border, muted = p["border"], p["muted"]
        else:
            pink = 13 if colors >= 16 else curses.COLOR_MAGENTA
            if curses.can_change_color() and pink < colors:
                try:
                    curses.init_color(pink, *BILIBILI_PINK_RGB)
                except curses.error:
                    pass
            text = bright = curses.COLOR_WHITE
            blue, gold = curses.COLOR_CYAN, curses.COLOR_YELLOW
            green, red = curses.COLOR_GREEN, curses.COLOR_RED
            border = muted = -1

        # 全部用前景色 + 透明背景，不再铺实心色块
        curses.init_pair(1, pink, -1)            # brand: 品牌粉
        curses.init_pair(2, pink, -1)            # accent: 粉色强调（选中边框/指针）
        curses.init_pair(3, bright, -1)          # title: 高亮标题
        curses.init_pair(4, pink, -1)            # selected: 选中项（纯粉字，无底色）
        curses.init_pair(5, blue, -1)            # info: 次级信息（UP主/数据）
        curses.init_pair(6, gold, -1)            # star: 收藏星标
        curses.init_pair(7, green, -1)           # ok: 成功状态
        curses.init_pair(8, red, -1)             # err: 错误状态
        curses.init_pair(9, border, -1)          # border: 边框
        curses.init_pair(10, muted, -1)          # muted: 弱化文本
        curses.init_pair(11, blue, -1)           # section: 区块小标题
        curses.init_pair(12, text, -1)           # body: 正文
        self._dim_extras = colors < 256          # 16 色没有专用灰，用 A_DIM 模拟
        self.use_colors = True

    def attr(self, name: str) -> int:
        import curses

        if not self.use_colors:
            return {
                "header": curses.A_BOLD,
                "brand": curses.A_BOLD,
                "accent": curses.A_BOLD,
                "title": curses.A_BOLD,
                "selected": curses.A_BOLD,
                "section": curses.A_BOLD,
                "info": curses.A_NORMAL,
                "body": curses.A_NORMAL,
                "star": curses.A_BOLD,
                "ok": curses.A_NORMAL,
                "err": curses.A_BOLD,
                "border": curses.A_DIM,
                "muted": curses.A_DIM,
                "tab_active": curses.A_BOLD | curses.A_UNDERLINE,
            }.get(name, curses.A_NORMAL)
        dim = curses.A_DIM if getattr(self, "_dim_extras", False) else 0
        pair_map = {
            "header": (1, curses.A_BOLD),
            "brand": (1, curses.A_BOLD),
            "accent": (2, curses.A_BOLD),
            "title": (3, curses.A_BOLD),
            "selected": (4, curses.A_BOLD),
            "section": (11, curses.A_BOLD),
            "info": (5, 0),
            "body": (12, 0),
            "star": (6, curses.A_BOLD),
            "ok": (7, 0),
            "err": (8, curses.A_BOLD),
            "border": (9, dim),
            "muted": (10, dim),
            "tab_active": (1, curses.A_BOLD | curses.A_UNDERLINE),
        }
        pair, extra = pair_map.get(name, (3, 0))
        return curses.color_pair(pair) | extra

    def attr_header(self) -> int:
        return self.attr("header")

    def attr_accent(self) -> int:
        return self.attr("accent")

    def attr_title(self) -> int:
        return self.attr("title")

    def attr_selected(self) -> int:
        return self.attr("selected")

    def attr_muted(self) -> int:
        return self.attr("muted")

    # ---------- state helpers ----------

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

    def current_comments_loading(self) -> bool:
        key = self._cache_key(self.selected_item)
        return key is not None and key in self._comment_inflight

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
            self.set_status("没有可返回的列表状态")
            return
        state = self.list_stack.pop()
        self.mode = state.mode
        self.page = state.page
        self.keyword = state.keyword
        self.selected_index = state.selected_index
        self.channel_index = state.channel_index
        self.detail_mode = False
        self.start_load_items(restore_index=state.selected_index, status=f"正在返回: {self.title}")

    def clamp_selection(self) -> None:
        if not self.items:
            self.selected_index = 0
            return
        self.selected_index = max(0, min(self.selected_index, len(self.items) - 1))

    def move_selection(self, delta: int) -> None:
        if not self.items:
            return
        new_index = max(0, min(len(self.items) - 1, self.selected_index + delta))
        if new_index != self.selected_index:
            self.selected_index = new_index
            self._detail_lines_cache = None
            self._schedule_comment_load()
            self._dirty = True

    def clamp_detail_scroll(self, width: int, height: int) -> None:
        lines = self.get_detail_lines(max(20, width))
        max_scroll = max(0, len(lines) - height)
        self.detail_scroll = max(0, min(self.detail_scroll, max_scroll))

    def get_detail_lines(self, width: int) -> list[str]:
        item = self.current_detail_item()
        if item is None:
            return ["没有结果。"]
        comments = self.current_comments()
        comment_error = self.current_comment_error()
        cache_token = (self._cache_key(item), width, len(comments), comment_error, id(item))
        if self._detail_lines_cache and self._detail_lines_cache[0] == cache_token:
            return self._detail_lines_cache[1]
        lines = build_detail_lines(item, width)
        if comment_error and not comments:
            lines.extend(["", f"评论加载失败: {comment_error}", "提示: 按 o 在浏览器中查看完整评论"])
        if comments:
            lines.extend(["", "💬 热评:"])
            for index, comment in enumerate(comments, start=1):
                header = f"{index}. 👤 {comment.author} · 👍 {human_count(comment.like)} · 📅 {format_timestamp(comment.ctime)}"
                lines.append(header)
                lines.extend(wrap_display(comment.message or "暂无评论内容", width=max(20, width)))
                lines.append("")
        self._detail_lines_cache = (cache_token, lines)
        return lines

    # ---------- data loading ----------

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
        self._detail_lines_cache = None

    def _fetch_channel_items(self, channel: dict[str, Any], page: int) -> list[VideoItem]:
        source = channel["source"]
        if source == "recommend":
            return self.client.recommend(page=page, page_size=self.limit)
        if source == "popular":
            return self.client.popular(page=page, page_size=self.limit)
        if source == "precious":
            return self.client.precious(page=page, page_size=self.limit)
        return self.client.region_ranking(channel["rid"], page=page, page_size=self.limit)

    def load_items(self, *, force_comments: bool = False) -> None:
        self.detail_mode = False
        self.detail_scroll = 0
        self._detail_lines_cache = None
        if self.mode == "search" and self.keyword:
            self.items = self.client.search(self.keyword, page=self.page, page_size=self.limit)
        elif self.mode == "history":
            self.items = self.history_store.get_recent_videos(self.limit)
        elif self.mode == "favorites":
            self.items = self.history_store.get_favorite_videos(self.limit)
        else:
            self.refresh_home_meta()
            self.items = self._fetch_channel_items(self.active_channel(), self.page)
        self.clamp_selection()
        self.ensure_comments_for_selected(force=force_comments)
        self.set_status(f"已加载 {len(self.items)} 条结果")

    def start_load_items(self, *, force_comments: bool = False, restore_index: int | None = None, status: str = "正在加载...") -> None:
        self.detail_mode = False
        self.detail_scroll = 0
        self._detail_lines_cache = None
        # 任何导航都要让仍在途的旧请求失效，包括切到本地的 history/favorites
        self._generation += 1
        if self.mode in {"history", "favorites"}:
            if self.mode == "history":
                self.items = self.history_store.get_recent_videos(self.limit)
            else:
                self.items = self.history_store.get_favorite_videos(self.limit)
            if restore_index is not None:
                self.selected_index = restore_index
            self.clamp_selection()
            self._schedule_comment_load(immediate=force_comments)
            self.set_status(f"已加载 {len(self.items)} 条结果")
            return

        generation = self._generation
        mode, page, keyword = self.mode, self.page, self.keyword
        channel = self.active_channel()
        need_home_meta = mode == "hot" and (force_comments or not self.default_search_keyword or not self.trending_keywords_cache)

        def work() -> Any:
            default_kw = None
            trending = None
            if need_home_meta:
                try:
                    default_kw = self.client.search_default()
                except BilibiliAPIError:
                    default_kw = None
                try:
                    trending = self.client.trending_keywords(6)
                except BilibiliAPIError:
                    trending = None
            if mode == "search" and keyword:
                items = self.client.search(keyword, page=page, page_size=self.limit)
            else:
                items = self._fetch_channel_items(channel, page)
            return items, default_kw, trending

        def apply(result: Any) -> None:
            if generation != self._generation:
                return
            items, default_kw, trending = result
            self.items = items
            if default_kw:
                self.default_search_keyword = default_kw
            if trending:
                self.trending_keywords_cache = trending
            if restore_index is not None:
                self.selected_index = restore_index
            self.clamp_selection()
            self._detail_lines_cache = None
            self.set_status(f"已加载 {len(self.items)} 条结果")
            self._schedule_comment_load(immediate=force_comments)

        self._submit(work, apply, status)

    def switch_mode(self, mode: str, *, page: int | None = None, keyword: str | None = None, push_current: bool = True) -> None:
        if push_current:
            self.push_list_state()
        self.mode = mode
        self.page = page if page is not None else 1
        if keyword is not None:
            self.keyword = keyword
        self.selected_index = 0
        self.start_load_items()

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
        self.start_load_items()

    def cycle_channel(self, step: int) -> None:
        target = (self.channel_index + step) % len(self.channels)
        self.set_channel(target)

    def refresh_current_view(self) -> None:
        if self.mode == "hot":
            self.refresh_home_meta(force=True)
        self.load_items(force_comments=True)
        self.set_status(f"已刷新: {self.title}")

    def refresh_current_view_async(self) -> None:
        self.start_load_items(force_comments=True, status=f"正在刷新: {self.title}")

    def refresh_comments(self) -> None:
        if self.selected_item is None:
            self.set_status("当前没有可加载评论的视频")
            return
        self.ensure_comments_for_selected(force=True)
        comment_error = self.current_comment_error()
        if comment_error:
            self.set_status(f"评论加载失败: {comment_error}", sticky=True)
            return
        comment_count = len(self.current_comments())
        self.set_status(f"已加载评论 {comment_count} 条")

    def refresh_comments_async(self) -> None:
        if self.selected_item is None:
            self.set_status("当前没有可加载评论的视频")
            return
        self.set_status("正在加载评论...", sticky=True)
        self._start_comment_load(force=True, announce=True)

    def toggle_selected_favorite(self) -> None:
        item = self.current_detail_item() if self.detail_mode else self.selected_item
        if item is None:
            self.set_status("当前没有可收藏的视频")
            return
        is_added = self.history_store.toggle_favorite(item)
        message = f"{'已收藏' if is_added else '已取消收藏'}: {truncate_display(item.title, 40)}"
        if self.mode == "favorites":
            self.load_items()
        self.set_status(message)

    def play_selected_audio(self) -> None:
        item = self.current_detail_item() if self.detail_mode else self.selected_item
        if item is None:
            self.set_status("当前没有可播放音频的视频")
            return
        self.history_store.add_video(item)
        self.set_status(audio.audio_action_for_item(self.client, item))
        self._refresh_audio_state()

    def play_selected_audio_async(self) -> None:
        item = self.current_detail_item() if self.detail_mode else self.selected_item
        if item is None:
            self.set_status("当前没有可播放音频的视频")
            return
        self.history_store.add_video(item)

        def apply(message: str) -> None:
            self.set_status(message)
            self._refresh_audio_state()

        self._submit(
            lambda: audio.audio_action_for_item(self.client, item),
            apply,
            "正在解析音频流...",
        )

    def stop_audio(self) -> None:
        self.set_status(audio.stop_audio_playback())
        self._refresh_audio_state()

    def open_selected(self) -> None:
        item = self.selected_item
        if item is None:
            self.set_status("当前没有可打开的视频")
            return
        self.history_store.add_video(item)
        webbrowser.open(item.url)
        self.set_status(f"已打开: {item.url}")

    def load_selected_detail(self, enter_detail_mode: bool = True) -> None:
        item = self.selected_item
        if item is None:
            self.set_status("当前没有可查看的视频")
            return
        key = self._cache_key(item)
        if key is None:
            self.set_status("当前视频缺少可查询标识")
            return
        self.detail_cache[key] = self.client.video(key)
        self.history_store.add_video(self.detail_cache[key])
        self.detail_scroll = 0
        self.detail_mode = enter_detail_mode
        self._detail_lines_cache = None
        self.set_status(f"已加载详情: {item.title}")

    def load_selected_detail_async(self) -> None:
        item = self.selected_item
        if item is None:
            self.set_status("当前没有可查看的视频")
            return
        key = self._cache_key(item)
        if key is None:
            self.set_status("当前视频缺少可查询标识")
            return
        if key in self.detail_cache:
            self.history_store.add_video(self.detail_cache[key])
            self.detail_scroll = 0
            self.detail_mode = True
            self._detail_lines_cache = None
            self.set_status(f"已加载详情: {item.title}")
            self._schedule_comment_load(immediate=True)
            return

        def apply(detail: VideoItem) -> None:
            self.detail_cache[key] = detail
            self.history_store.add_video(detail)
            self.detail_scroll = 0
            self.detail_mode = True
            self._detail_lines_cache = None
            self.set_status(f"已加载详情: {detail.title}")
            self._schedule_comment_load(immediate=True)

        self._submit(lambda: self.client.video(key), apply, "正在加载详情...")

    def rerun_last_search(self) -> None:
        keywords = self.history_store.get_recent_keywords(1)
        if not keywords:
            self.set_status("没有最近搜索记录")
            return
        self.switch_mode("search", page=1, keyword=keywords[0])

    # ---------- input ----------

    def prompt_input(self, stdscr: Any, prompt: str, initial: str = "") -> str | None:
        import curses

        buffer = list(initial)
        cursor = len(buffer)
        curses.curs_set(1)
        stdscr.timeout(-1)
        try:
            while True:
                height, width = stdscr.getmaxyx()
                stdscr.move(height - 1, 0)
                stdscr.clrtoeol()
                text = f"{prompt}{''.join(buffer)}"
                try:
                    stdscr.addnstr(height - 1, 0, text, max(1, width - 1))
                except curses.error:
                    pass
                cursor_x = min(width - 1, display_width(prompt + "".join(buffer[:cursor])))
                try:
                    stdscr.move(height - 1, cursor_x)
                except curses.error:
                    pass
                stdscr.refresh()
                try:
                    key = stdscr.get_wch()
                except curses.error:
                    continue
                if key == "\x1b":
                    return None
                if key in ("\n", "\r"):
                    return "".join(buffer).strip()
                if key in (curses.KEY_BACKSPACE, "\b", "\x7f"):
                    if cursor > 0:
                        del buffer[cursor - 1]
                        cursor -= 1
                    continue
                if key == curses.KEY_DC:
                    if cursor < len(buffer):
                        del buffer[cursor]
                    continue
                if key == curses.KEY_LEFT:
                    cursor = max(0, cursor - 1)
                    continue
                if key == curses.KEY_RIGHT:
                    cursor = min(len(buffer), cursor + 1)
                    continue
                if key in (curses.KEY_HOME, "\x01"):
                    cursor = 0
                    continue
                if key in (curses.KEY_END, "\x05"):
                    cursor = len(buffer)
                    continue
                if key == "\x15":
                    del buffer[:cursor]
                    cursor = 0
                    continue
                if key == "\x0b":
                    del buffer[cursor:]
                    continue
                if key == "\x17":
                    end = cursor
                    while cursor > 0 and buffer[cursor - 1].isspace():
                        cursor -= 1
                    while cursor > 0 and not buffer[cursor - 1].isspace():
                        cursor -= 1
                    del buffer[cursor:end]
                    continue
                if isinstance(key, str) and key.isprintable():
                    buffer.insert(cursor, key)
                    cursor += 1
        finally:
            curses.curs_set(0)
            stdscr.timeout(TICK_MS)

    # ---------- drawing ----------

    def draw_help_overlay(self, stdscr: Any, height: int, width: int) -> None:
        import curses

        lines = [
            "帮助",
            "",
            "── 列表视图 ──",
            "j / k, ↑ / ↓   移动选中项（自动加载热评）",
            "Enter          打开详情页",
            "Esc / b        返回上一个列表",
            "/ 或 s         搜索，支持中文与行内编辑",
            "Tab / Shift+Tab 切换首页分区",
            "1-9            直接切换对应分区",
            "l              重跑最近一次搜索",
            "h              切回首页流",
            "v              查看历史",
            "m              查看收藏夹",
            "n / p          下一页 / 上一页",
            "d              使用默认搜索词搜索",
            "r              刷新当前页",
            "",
            "── 详情视图 ──",
            "j / k          滚动，PgUp/PgDn 翻页",
            "r / c          刷新详情评论",
            "Esc / b        返回列表",
            "",
            "── 通用 ──",
            "f 收藏  a 播放/暂停音频  x 停止音频",
            "o 浏览器打开  c 加载评论  ? 帮助  q 退出",
            "",
            f"最近搜索: {', '.join(self.history_store.get_recent_keywords(3)) or '无'}",
        ]
        box_width = min(width - 4, max(56, width * 3 // 4))
        box_height = min(height - 4, len(lines) + 2)
        start_y = max(1, (height - box_height) // 2)
        start_x = max(2, (width - box_width) // 2)
        win = stdscr.derwin(box_height, box_width, start_y, start_x)
        win.erase()
        try:
            win.box()
        except curses.error:
            pass
        for index, line in enumerate(lines[: box_height - 2], start=1):
            if index == 1:
                attr = self.attr("brand")
            elif line.startswith("──"):
                attr = self.attr("section")
            elif line.startswith("最近搜索"):
                attr = self.attr("muted")
            else:
                attr = self.attr("body")
            try:
                win.addnstr(index, 2, line, box_width - 4, attr)
            except curses.error:
                pass

    def draw_box(
        self,
        stdscr: Any,
        y: int,
        x: int,
        height: int,
        width: int,
        label: str | None = None,
        *,
        selected: bool = False,
        label_attr: int | None = None,
    ) -> None:
        import curses

        if height <= 1 or width <= 1:
            return

        border_attr = self.attr("accent") if selected else self.attr("border")
        top = "╭" + "─" * (width - 2) + "╮"
        bottom = "╰" + "─" * (width - 2) + "╯"

        try:
            stdscr.addnstr(y, x, top, width, border_attr)
            for i in range(1, height - 1):
                stdscr.addnstr(y + i, x, "│", 1, border_attr)
                stdscr.addnstr(y + i, x + width - 1, "│", 1, border_attr)
            stdscr.addnstr(y + height - 1, x, bottom, width, border_attr)
        except curses.error:
            pass

        if label:
            label_text = f"╴{label}╶"
            if label_attr is not None:
                resolved_label_attr = label_attr
            elif selected:
                resolved_label_attr = self.attr("accent")
            else:
                resolved_label_attr = self.attr("section")
            try:
                stdscr.addnstr(y, x + 2, label_text, width - 4, resolved_label_attr)
            except curses.error:
                pass

    def _now_playing_token(self, width: int) -> str | None:
        if self._audio_state is None:
            return None
        icon = "⏸" if self._audio_state.paused else "♪"
        return truncate_display(f"{icon} {self._audio_state.title}", max(8, width))

    def _refresh_audio_state(self) -> None:
        try:
            self._audio_state = audio.load_audio_playback_state()
        except Exception:  # noqa: BLE001 — 状态文件损坏不应拖垮界面
            self._audio_state = None

    def draw_banner(self, stdscr: Any, y: int, width: int) -> int:
        banner_height = 6
        self.draw_box(stdscr, y, 0, banner_height, width, "发现")
        headline = "哔哩哔哩 · 终端版"
        stdscr.addnstr(y + 1, centered_x(width, headline, 2), headline, width - 4, self.attr("brand"))
        if self.mode == "search" and self.keyword:
            query = truncate_display(self.keyword, max(12, width - 24))
            search_text = f"🔍 {query}"
        else:
            default_word = self.default_search_keyword or "按 / 开始搜索"
            search_text = f"🔍 {truncate_display(default_word, max(12, width - 24))}"
        search_x = centered_x(width, search_text, 2)
        stdscr.addnstr(y + 2, search_x, search_text, max(1, width - search_x - 2), self.attr("title"))
        if self.mode == "hot":
            channel_label = self.active_channel()["label"]
        elif self.mode == "favorites":
            channel_label = "收藏夹"
        elif self.mode == "history":
            channel_label = "最近浏览"
        else:
            channel_label = "搜索"
        section_line = f"{channel_label} · 第 {self.page} 页"
        stdscr.addnstr(y + 3, centered_x(width, section_line, 2), section_line, width - 4, self.attr("info"))
        hot_words = " · ".join(self.trending_keywords_cache[:3]) if self.trending_keywords_cache else "热点内容 · 分区导航 · 精选视频"
        subline = f"🔥 {truncate_display(hot_words, max(16, width - 12))}"
        stdscr.addnstr(y + 4, centered_x(width, subline, 2), subline, width - 4, self.attr("muted"))
        return banner_height

    def draw_category_row(self, stdscr: Any, y: int, width: int) -> int:
        chips = [f"{index + 1} {channel['label']}" for index, channel in enumerate(self.channels)]
        widths = [display_width(chip) for chip in chips]
        gap = 3
        start = 0
        if self.mode == "hot":
            # 保证当前分区始终可见：不够宽时从更后面的 chip 开始画
            while start < self.channel_index:
                x = 0
                visible_through_active = False
                for index in range(start, len(chips)):
                    if x + widths[index] >= width - 2:
                        break
                    if index == self.channel_index:
                        visible_through_active = True
                    x += widths[index] + gap
                if visible_through_active:
                    break
                start += 1
        x = 0
        if start > 0:
            stdscr.addnstr(y, x, "‹", 1, self.attr("muted"))
            x += 2
        truncated = False
        for index in range(start, len(chips)):
            chip = chips[index]
            chip_width = widths[index]
            if x + chip_width >= width - 2:
                truncated = True
                break
            active = index == self.channel_index and self.mode == "hot"
            attr = self.attr("selected") if active else self.attr("muted")
            stdscr.addnstr(y, x, chip, chip_width, attr)
            x += chip_width + gap
        if truncated and x < width - 1:
            stdscr.addnstr(y, x, "›", 1, self.attr("muted"))
        return 1

    def selected_card_item(self) -> VideoItem | None:
        return self.selected_item

    def draw_featured_card(self, stdscr: Any, y: int, x: int, height: int, width: int, item: VideoItem | None, selected: bool) -> None:
        self.draw_box(stdscr, y, x, height, width, "今日精选", selected=selected)
        if item is None:
            stdscr.addnstr(y + 2, x + 2, "没有可展示的内容", width - 4, self.attr("muted"))
            return

        is_fav = self.history_store.is_favorite(item)
        title_text = f"★ {item.title}" if is_fav else item.title
        if height < 9:
            stdscr.addnstr(y + 1, x + 2, truncate_display(title_text, width - 4), width - 4, self.attr("title"))
            stdscr.addnstr(y + 2, x + 2, truncate_display(f"UP {item.author}", width - 4), width - 4, self.attr("info"))
            stdscr.addnstr(y + height - 2, x + 2, "⏎ 查看详情", width - 4, self.attr("muted"))
            return

        title_attr = self.attr("selected") if selected else self.attr("title")
        title_lines = wrap_display(title_text, max(12, width - 4))
        content_y = y + 1
        max_title_lines = 2 if height < 16 else 3
        shown_title_lines = title_lines[:max_title_lines]
        for line in shown_title_lines:
            stdscr.addnstr(content_y, x + 2, line, width - 4, title_attr)
            content_y += 1

        stdscr.addnstr(content_y, x + 2, truncate_display(f"UP {item.author}", width - 4), width - 4, self.attr("info"))
        content_y += 1
        stats_line = truncate_display(
            f"▶ {human_count(item.play)} 播放 · ≣ {human_count(item.danmaku)} 弹幕 · ◷ {item.duration}",
            width - 4,
        )
        stdscr.addnstr(content_y, x + 2, stats_line, width - 4, self.attr("info"))
        content_y += 1
        meta_lines = [
            truncate_display(f"{format_timestamp(item.pubdate)} · {item.bvid or item.aid}", width - 4),
        ]
        for meta_line in meta_lines:
            stdscr.addnstr(content_y, x + 2, meta_line, width - 4, self.attr("muted"))
            content_y += 1

        sections: list[tuple[str, list[str]]] = []
        desc_lines = wrap_display(item.description or "暂无简介", width=max(12, width - 4))
        sections.append(("¶ 简介", desc_lines))

        hot_lines = [f"{index + 1}. {word}" for index, word in enumerate(self.trending_keywords_cache[:6])]
        if hot_lines:
            sections.append(("🔥 热搜速览", hot_lines))

        recent_keywords = self.history_store.get_recent_keywords(3)
        if recent_keywords:
            sections.append(("🔍 最近搜索", recent_keywords))

        recent_videos = [
            truncate_display(history_item.title, width - 4)
            for history_item in self.history_store.get_recent_videos(3)
            if (history_item.bvid or history_item.aid) != (item.bvid or item.aid)
        ]
        if recent_videos:
            sections.append(("◷ 最近浏览", recent_videos[:3]))

        sections.append(("⌘ 快捷操作", ["⏎ 查看详情", "a 播放/暂停音频", "x 停止音频", "f 收藏当前视频", "m 打开收藏夹"]))

        footer_y = y + height - 2
        available_body_lines = max(0, footer_y - content_y - 1)
        body_cursor = content_y + 1
        for section_title, lines in sections:
            if available_body_lines <= 0:
                break
            stdscr.addnstr(body_cursor, x + 2, section_title, width - 4, self.attr("section"))
            body_cursor += 1
            available_body_lines -= 1
            if available_body_lines <= 0:
                break
            for line in lines:
                if available_body_lines <= 0:
                    break
                stdscr.addnstr(body_cursor, x + 2, truncate_display(line, width - 4), width - 4, self.attr("body"))
                body_cursor += 1
                available_body_lines -= 1
        stdscr.addnstr(y + height - 2, x + 2, "⏎ 查看详情", width - 4, self.attr("muted"))

    def draw_grid_card(self, stdscr: Any, y: int, x: int, height: int, width: int, index: int, item: VideoItem, selected: bool) -> None:
        label = f"{index + 1:02d}"
        self.draw_box(
            stdscr,
            y,
            x,
            height,
            width,
            label,
            selected=selected,
            label_attr=self.attr("selected") if selected else None,
        )
        title_attr = self.attr("selected") if selected else self.attr("title")
        is_fav = self.history_store.is_favorite(item)
        prefix = "★ " if is_fav else ""
        pointer = "❯ " if selected else ""
        title = f"{pointer}{prefix}{item.title}"
        stdscr.addnstr(y + 1, x + 2, truncate_display(title, width - 4), width - 4, title_attr)
        stdscr.addnstr(y + 2, x + 2, truncate_display(f"UP {item.author}", width - 4), width - 4, self.attr("info"))
        if height >= 5:
            metrics = f"▶ {human_count(item.play)} · ◷ {item.duration}"
            stdscr.addnstr(y + 3, x + 2, truncate_display(metrics, width - 4), width - 4, self.attr("muted"))

    def draw_comments_panel(self, stdscr: Any, y: int, x: int, height: int, width: int) -> None:
        panel_label = "评论预览" if self.mode == "favorites" else "热评"
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
                attr = self.attr("err") if index == 1 else self.attr("muted")
                stdscr.addnstr(y + index, x + 2, truncate_display(line, width - 4), width - 4, attr)
            return
        if not comments:
            if self.current_comments_loading():
                stdscr.addnstr(y + 1, x + 2, "热评加载中...", width - 4, self.attr("muted"))
            elif self.current_comments_loaded():
                stdscr.addnstr(y + 1, x + 2, "当前视频暂无可显示热评", width - 4, self.attr("muted"))
                stdscr.addnstr(y + 2, x + 2, "按 r 刷新页面，按 o 浏览器查看", width - 4, self.attr("muted"))
            else:
                stdscr.addnstr(y + 1, x + 2, "停留片刻自动加载热评", width - 4, self.attr("muted"))
                stdscr.addnstr(y + 2, x + 2, "按 c 立即加载，r 刷新当前视图", width - 4, self.attr("muted"))
            return

        cursor = y + 1
        available = height - 2
        for index, comment in enumerate(comments, start=1):
            if available <= 0:
                break
            header = truncate_display(
                f"❝ {comment.author} · ♡ {human_count(comment.like)} · {format_timestamp(comment.ctime)}",
                width - 4,
            )
            stdscr.addnstr(cursor, x + 2, header, width - 4, self.attr("info"))
            cursor += 1
            available -= 1
            if available <= 0:
                break
            for line in wrap_display(comment.message or "暂无评论内容", width=max(12, width - 4)):
                if available <= 0:
                    break
                stdscr.addnstr(cursor, x + 2, line, width - 4, self.attr("body"))
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
            stdscr.addnstr(start_y, start_x, "当前没有选中的视频", width, self.attr("muted"))
            return

        title = f"★ {item.title}" if self.history_store.is_favorite(item) else item.title
        summary_lines = [
            title,
            f"UP {item.author}",
            f"▶ {human_count(item.play)} 播放 · ≣ {human_count(item.danmaku)} 弹幕 · ◷ {item.duration}",
            f"发布于 {format_timestamp(item.pubdate)} · {item.bvid or item.aid}",
            "",
            "🔗 链接",
            truncate_display(item.url, width=width),
            "",
            "¶ 简介",
        ]
        desc_lines = wrap_display(item.description or "暂无简介", width=max(20, width))
        lines = summary_lines + desc_lines
        for offset, line in enumerate(lines[:height]):
            if offset == 0:
                attr = self.attr("title")
            elif offset in (1, 2, 3):
                attr = self.attr("info")
            elif line in ("🔗 链接", "¶ 简介"):
                attr = self.attr("section")
            else:
                attr = self.attr("body")
            stdscr.addnstr(start_y + offset, start_x, line, width, attr)

    def draw_favorites_list(self, stdscr: Any, y: int, x: int, height: int, width: int) -> None:
        label = f"收藏列表 · {len(self.items)}"
        self.draw_box(stdscr, y, x, height, width, label)
        if height < 4:
            return
        if not self.items:
            stdscr.addnstr(y + 2, x + 2, "收藏夹还是空的", width - 4, self.attr("muted"))
            if height >= 6:
                stdscr.addnstr(y + 3, x + 2, "看到喜欢的视频时按 f 就能加入收藏。", width - 4, self.attr("muted"))
            return

        cursor = y + 1
        for index, item in enumerate(self.items):
            remaining = y + height - cursor - 1
            if remaining < 2:
                break
            selected = index == self.selected_index
            prefix = "❯ " if selected else "  "
            title = f"{prefix}★ {item.title}"
            title_attr = self.attr("selected") if selected else self.attr("title")
            stdscr.addnstr(cursor, x + 2, truncate_display(title, width - 4), width - 4, title_attr)
            cursor += 1

            meta = f"  {item.author} · ▶ {human_count(item.play)} · ◷ {item.duration}"
            stdscr.addnstr(cursor, x + 2, truncate_display(meta, width - 4), width - 4, self.attr("info") if selected else self.attr("muted"))
            cursor += 1

            if remaining >= 4:
                ref_line = f"  {item.bvid or item.aid} · {format_timestamp(item.pubdate)}"
                stdscr.addnstr(cursor, x + 2, truncate_display(ref_line, width - 4), width - 4, self.attr("muted"))
                cursor += 1

            if cursor < y + height - 1:
                stdscr.addnstr(cursor, x + 2, "┄" * max(1, min(width - 4, width - 4)), width - 4, self.attr("border"))
                cursor += 1

    def draw_favorites_view(self, stdscr: Any, height: int, width: int) -> None:
        self._draw_top_bar(stdscr, width, "我的收藏", f"共 {len(self.items)} 条")

        selected = self.selected_item
        now_playing = self._now_playing_token(max(10, width // 2))
        if now_playing:
            subtitle = now_playing
            subtitle_attr = self.attr("ok") if self._audio_state and not self._audio_state.paused else self.attr("star")
        elif selected is None:
            subtitle = "本地收藏，稍后可用 o 在浏览器继续看"
            subtitle_attr = self.attr("muted")
        else:
            subtitle = truncate_display(
                f"当前选中 · {selected.author} · ▶ {human_count(selected.play)} · a 播放/暂停 · x 停止 · o 浏览器打开",
                max(20, width - 2),
            )
            subtitle_attr = self.attr("muted")
        stdscr.addnstr(1, 1, subtitle, width - 2, subtitle_attr)

        content_top = 3
        content_height = max(1, height - content_top - 3)
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

    def _draw_top_bar(self, stdscr: Any, width: int, title: str, right_text: str) -> None:
        # 左侧品牌标题（粉），右侧上下文（弱化）
        stdscr.addnstr(0, 0, title, width - 1, self.attr("brand"))
        right_x = max(0, width - display_width(right_text) - 1)
        if right_x > display_width(title):
            stdscr.addnstr(0, right_x, right_text, width - right_x - 1, self.attr("muted"))

    def _draw_tab_row(self, stdscr: Any, y: int, width: int) -> None:
        tabs = [
            ("首页", "hot"),
            ("搜索", "search"),
            ("历史", "history"),
            ("收藏", "favorites"),
        ]
        tab_x = 1
        for label, mode in tabs:
            active = self.mode == mode
            chip = f"{label}"
            chip_width = display_width(chip)
            if tab_x + chip_width >= width - 1:
                break
            attr = self.attr("tab_active") if active else self.attr("muted")
            stdscr.addnstr(y, tab_x, chip, chip_width, attr)
            tab_x += chip_width + 3

        now_playing = self._now_playing_token(max(10, width // 3))
        if now_playing:
            hint = now_playing
            hint_attr = self.attr("ok") if self._audio_state and not self._audio_state.paused else self.attr("star")
        elif self.mode == "search" and self.keyword:
            hint = f"当前搜索：{truncate_display(self.keyword, max(10, width // 4))}"
            hint_attr = self.attr("muted")
        elif self.mode == "favorites":
            hint = "a 播放/暂停 · x 停止 · o 打开"
            hint_attr = self.attr("muted")
        else:
            hint = "Tab 切换分区 · / 搜索 · ? 帮助"
            hint_attr = self.attr("muted")
        hint_x = max(0, width - display_width(hint) - 1)
        if hint_x > tab_x:
            stdscr.addnstr(y, hint_x, hint, width - hint_x - 1, hint_attr)

    def draw_split_view(self, stdscr: Any, height: int, width: int) -> None:
        self._draw_top_bar(stdscr, width, "哔哩哔哩终端", f"{self.mode_token()} · 第 {self.page} 页")
        self._draw_tab_row(stdscr, 1, width)
        stdscr.addnstr(2, 0, "─" * max(1, width - 1), width - 1, self.attr("border"))

        banner_height = self.draw_banner(stdscr, 3, width)
        chips_height = self.draw_category_row(stdscr, 3 + banner_height, width)

        content_top = 3 + banner_height + chips_height + 1
        content_height = max(1, height - content_top - 3)
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
        header = "详情页"
        header_right_full = "j/k 滚动  a 播放/暂停  x 停止  f 收藏  o 浏览器打开  c 刷新评论  Esc 返回  ? 帮助"
        header_right_compact = "j/k 滚动  Esc 返回  ? 帮助"
        header_right = header_right_full if display_width(header) + display_width(header_right_full) < width - 2 else header_right_compact
        self._draw_top_bar(stdscr, width, header, header_right)
        item = self.current_detail_item()
        title = item.title if item else "没有结果"
        if item and self.history_store.is_favorite(item):
            title = f"★ {title}"
        content_top = 2
        content_height = max(5, height - 5)
        self.draw_box(stdscr, content_top, 0, content_height, width, "视频详情")
        stdscr.addnstr(content_top + 1, 2, truncate_display(title, width - 4), width - 4, self.attr("title"))
        detail_lines = self.get_detail_lines(max(20, width - 4))
        visible_capacity = max(1, content_height - 4)
        self.clamp_detail_scroll(width - 4, visible_capacity)
        visible_lines = detail_lines[self.detail_scroll : self.detail_scroll + visible_capacity]
        for offset, line in enumerate(visible_lines):
            if "💬 热评:" in line or "📝 简介:" in line:
                attr = self.attr("section")
            elif line.startswith(("👤", "🔗", "🕒", "📅", "▶", "≡", "👍", "⭐", "🌐")):
                attr = self.attr("info")
            elif line.startswith(tuple(f"{n}. " for n in range(1, 10))) and "👍" in line:
                attr = self.attr("info")
            else:
                attr = self.attr("body")
            stdscr.addnstr(content_top + 2 + offset, 2, line, width - 4, attr)
        footer = f"⇕ {self.detail_scroll + 1}-{self.detail_scroll + len(visible_lines)} / {len(detail_lines)}"
        stdscr.addnstr(content_top + content_height - 2, 2, footer, width - 4, self.attr("muted"))

    def draw(self, stdscr: Any) -> None:
        import curses

        stdscr.erase()
        height, width = stdscr.getmaxyx()
        if height < 12 or width < 70:
            stdscr.addnstr(0, 0, "终端太小，至少需要 70x12。", max(1, width - 1))
            stdscr.refresh()
            return

        try:
            if self.detail_mode:
                self.draw_detail_view(stdscr, height, width)
            elif self.mode == "favorites":
                self.draw_favorites_view(stdscr, height, width)
            else:
                self.draw_split_view(stdscr, height, width)

            stdscr.addnstr(height - 2, 0, "─" * max(1, width - 1), width - 1, self.attr("border"))
            if self.detail_mode:
                shortcuts = "j/k 滚动  a 播放/暂停  x 停止  f 收藏  o 浏览器打开  r/c 刷新评论  b 返回  q 退出"
            elif self.mode == "favorites":
                shortcuts = "j/k 移动  Enter 详情  a 播放/暂停  x 停止  f 取消收藏  o 浏览器打开  c 评论  b 返回  q 退出"
            else:
                shortcuts = "Tab 分区  1-9 直选  / 搜索  a 播放/暂停  x 停止  f 收藏  m 收藏夹  c 评论  Enter 详情  q 退出"
            stdscr.addnstr(height - 2, 2, shortcuts, width - 4, self.attr("muted"))
            if self._loading > 0:
                spinner = SPINNER_FRAMES[self._spinner_index]
                status_line = f"{spinner} {self.status}" if self.status else f"{spinner} 加载中..."
                status_attr = self.attr("accent")
            elif self.status:
                # 根据状态语义着色：失败用红，完成用绿，其余强调色
                if "失败" in self.status or "错误" in self.status:
                    status_attr = self.attr("err")
                elif self.status.startswith(("已", "已加载", "已收藏", "已停止", "已暂停", "已继续")):
                    status_attr = self.attr("ok")
                else:
                    status_attr = self.attr("accent")
                status_line = f"› {self.status}"
            else:
                status_line = ""
            if status_line:
                stdscr.addnstr(height - 1, 0, status_line, width - 1, status_attr)
            if self.show_help:
                self.draw_help_overlay(stdscr, height, width)
        except curses.error:
            pass
        stdscr.refresh()

    # ---------- main loop ----------

    def handle_detail_key(self, key: int) -> bool:
        import curses

        if key in (ord("?"),):
            self.show_help = True
        elif key in (27, curses.KEY_LEFT, ord("b")):
            self.detail_mode = False
            self.detail_scroll = 0
            self.set_status("已返回列表")
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
            self.play_selected_audio_async()
        elif key == ord("x"):
            self.stop_audio()
        elif key == ord("f"):
            self.toggle_selected_favorite()
        elif key in (ord("c"), ord("r")):
            self.refresh_comments_async()
        elif key in (ord("q"), 3):
            return True
        return False

    def handle_list_key(self, stdscr: Any, key: int) -> bool:
        import curses

        if key in (ord("q"), 3):
            return True
        if key in (ord("?"),):
            self.show_help = True
        elif key in (curses.KEY_UP, ord("k")):
            self.move_selection(-1)
        elif key in (curses.KEY_DOWN, ord("j")):
            self.move_selection(1)
        elif key == ord("b"):
            self.restore_previous_state()
        elif key in (9,):
            self.cycle_channel(1)
        elif key == curses.KEY_BTAB:
            self.cycle_channel(-1)
        elif ord("1") <= key <= ord("9"):
            self.set_channel(key - ord("1"))
        elif key in (ord("g"),):
            self.move_selection(-len(self.items))
        elif key in (ord("G"),):
            self.move_selection(len(self.items))
        elif key in (10, 13, curses.KEY_RIGHT):
            self.load_selected_detail_async()
        elif key == ord("o"):
            self.open_selected()
        elif key == ord("a"):
            self.play_selected_audio_async()
        elif key == ord("x"):
            self.stop_audio()
        elif key == ord("r"):
            self.refresh_current_view_async()
        elif key == ord("c"):
            self.refresh_comments_async()
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
            keyword = self.default_search_keyword
            if keyword:
                self.history_store.add_keyword(keyword)
                self.switch_mode("search", keyword=keyword)
            else:
                def apply(fetched: str) -> None:
                    if fetched:
                        self.default_search_keyword = fetched
                        self.history_store.add_keyword(fetched)
                        self.switch_mode("search", keyword=fetched)
                    else:
                        self.set_status("当前没有默认搜索词")

                self._submit(self.client.search_default, apply, "正在获取默认搜索词...")
        elif key in (ord("/"), ord("s")):
            keyword = self.prompt_input(stdscr, "搜索关键词: ", self.keyword if self.mode == "search" else "")
            if keyword:
                self.history_store.add_keyword(keyword)
                self.switch_mode("search", keyword=keyword)
            else:
                self.set_status("已取消搜索")
        elif key in (ord("n"), curses.KEY_NPAGE):
            if self.mode in {"history", "favorites"}:
                self.set_status("当前列表没有分页")
            else:
                self.push_list_state()
                self.page += 1
                self.selected_index = 0
                self.start_load_items()
        elif key in (ord("p"), curses.KEY_PPAGE):
            if self.mode in {"history", "favorites"}:
                self.set_status("当前列表没有分页")
            elif self.page > 1:
                self.push_list_state()
                self.page -= 1
                self.selected_index = 0
                self.start_load_items()
            else:
                self.set_status("已经是第一页")
        return False

    def run(self, stdscr: Any) -> None:
        import curses

        self.init_theme()
        curses.curs_set(0)
        stdscr.keypad(True)
        stdscr.timeout(TICK_MS)
        self._refresh_audio_state()
        self.start_load_items()
        self._dirty = True
        while True:
            if self._dirty:
                self.draw(stdscr)
                self._dirty = False
            key = stdscr.getch()
            if key == -1:
                self._tick()
                continue
            self._dirty = True
            if key == curses.KEY_RESIZE:
                continue
            try:
                if self.show_help:
                    if key in (ord("?"), ord("q"), 27, 10, 13):
                        self.show_help = False
                    continue
                if self.detail_mode:
                    if self.handle_detail_key(key):
                        return
                    continue
                if self.handle_list_key(stdscr, key):
                    return
            except (BilibiliAPIError, ValueError) as exc:
                self.set_status(f"错误: {exc}", sticky=True)


def run_tui(client: BilibiliClient, history_store: HistoryStore) -> int:
    import curses

    def _main(stdscr: Any) -> None:
        BilibiliTUI(client, history_store).run(stdscr)

    curses.wrapper(_main)
    return 0
