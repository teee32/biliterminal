from __future__ import annotations

import webbrowser
from typing import TYPE_CHECKING

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Footer, Header, Input, ListItem, ListView, Static

from ...bilibili_cli import BilibiliAPIError, channel_shortcut_index_from_key
from ..utils import AudioStatus, DEFAULT_SEARCH_PLACEHOLDER, DEFAULT_STATUS_TEXT, FeedSnapshot, TextualAdapter, help_text
from ..widgets import AudioBar, CommentView, VideoList

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .detail import DetailScreen


class BaseFeedScreen(Screen[bool | None]):
    """Shared Textual list screen used by Home/Search/History/Favorites."""

    MODE_KIND = "feed"
    SHOW_SIDEBAR = False
    SHOW_SEARCH = False
    ALLOW_PAGING = True
    PAGE_SIZE = 10

    def __init__(
        self,
        *,
        adapter: TextualAdapter,
        initial_audio: AudioStatus | None = None,
        page: int = 1,
        keyword: str = "",
        channel_index: int = 0,
    ) -> None:
        super().__init__()
        self.adapter = adapter
        self.initial_audio = initial_audio or adapter.current_audio_status()
        self.page = page
        self.keyword = keyword
        self.channel_index = channel_index
        self.status_text = DEFAULT_STATUS_TEXT
        self.help_visible = False
        self.detail_cache: dict[str, tuple[str, list[str], list, str | None]] = {}
        self._detail_return_key: str | None = None
        self.snapshot = self.make_empty_snapshot("正在加载…")

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Vertical(id="page-shell"):
            yield Static("哔哩哔哩 bilibili · 为你推荐 / 热门内容流", id="page-masthead")
            with Horizontal(id="browser-layout"):
                if self.SHOW_SIDEBAR:
                    with Vertical(id="sidebar-pane", classes="panel panel-side"):
                        yield Static("主站导航", classes="panel-title")
                        yield Static("Tab / Shift+Tab 切换分区\n1-9 / 0 快速直达", id="sidebar-intro")
                        yield ListView(
                            *(ListItem(Static(self._channel_label(index), classes="channel-item")) for index in range(len(self.adapter.channels))),
                            id="channel-list",
                        )
                with Vertical(id="main-pane", classes="panel-main"):
                    with Vertical(id="hero-card", classes="surface-card"):
                        yield Static("", id="screen-title")
                        yield Static("", id="screen-subtitle")
                        yield Static("", id="screen-banner", classes="hidden")
                        yield Static("", id="screen-meta")
                    if self.SHOW_SEARCH:
                        yield Input(placeholder=DEFAULT_SEARCH_PLACEHOLDER, value=self.keyword, id="search-input")
                    with Vertical(id="feed-card", classes="surface-card"):
                        yield Static("", id="feed-section-title")
                        yield Static("", id="feed-section-hint")
                        yield VideoList(id="video-list")
                with Vertical(id="detail-pane", classes="panel panel-side"):
                    yield Static("视频情报", classes="panel-title")
                    yield Static("", id="detail-summary", classes="surface-card")
                    yield CommentView(id="comment-view", classes="surface-card")
        yield Static("", id="status-line")
        yield AudioBar(id="audio-bar")
        yield Static("", id="help-overlay", classes="hidden")
        yield Footer()

    def on_mount(self) -> None:
        if hasattr(self.app, "apply_theme_to_screen"):
            self.app.apply_theme_to_screen(self)
        if self.SHOW_SIDEBAR:
            self.query_one("#channel-list", ListView).index = self.channel_index
        self._update_help_overlay()
        self.apply_audio_status(self.initial_audio)
        self.load_feed(set_status=False)
        if self.SHOW_SEARCH and not self.keyword:
            self.focus_search()
        else:
            self.focus_video_list()

    def make_empty_snapshot(self, empty_message: str) -> FeedSnapshot:
        return FeedSnapshot(
            mode=self.MODE_KIND if self.MODE_KIND in {"home", "search", "history", "favorites"} else "home",
            title=self.screen_title(),
            videos=(),
            empty_message=empty_message,
            page=self.page,
            keyword=self.keyword,
            channel_index=self.channel_index,
        )

    def screen_title(self) -> str:
        return {
            "home": "首页推荐",
            "search": "搜索",
            "history": "最近浏览",
            "favorites": "收藏夹",
        }.get(self.MODE_KIND, "BiliTerminal")

    def subtitle_text(self) -> str:
        return "按 Tab / Shift+Tab / 1-9 / 0 快速切换分区"

    def banner_text(self) -> str:
        return ""

    def meta_text(self) -> str:
        recent = " / ".join(self.adapter.recent_keywords(3)) or "暂无"
        return f"最近搜索: {recent}"

    def fetch_snapshot(self) -> FeedSnapshot:
        raise NotImplementedError

    def load_feed(self, *, preserve_key: str | None = None, set_status: bool = True) -> None:
        selected_key = preserve_key or self.current_video_key()
        try:
            snapshot = self.fetch_snapshot()
            error_message: str | None = None
        except BilibiliAPIError as exc:
            snapshot = self.make_empty_snapshot(str(exc))
            error_message = str(exc)
        self.snapshot = snapshot
        video_list = self.query_one(VideoList)
        video_list.set_videos(list(snapshot.videos), selected_index=0)
        if selected_key:
            video_list.select_key(selected_key)
        self._refresh_header()
        self._refresh_preview(video_list.selected_video)
        if error_message:
            self.set_status(f"错误: {error_message}")
        elif set_status:
            if snapshot.videos:
                self.set_status(f"已加载 {len(snapshot.videos)} 条内容")
            else:
                self.set_status(snapshot.empty_message)

    def focus_video_list(self) -> None:
        self.query_one(VideoList).focus()

    def current_video(self):
        return self.query_one(VideoList).selected_video

    def current_video_key(self) -> str | None:
        return self.query_one(VideoList).selected_key()

    def set_status(self, message: str) -> None:
        self.status_text = message
        self.query_one("#status-line", Static).update(f"状态：{message}")

    def apply_audio_status(self, status: AudioStatus) -> None:
        self.query_one(AudioBar).set_audio_status(status)

    def _refresh_header(self) -> None:
        self.query_one("#screen-title", Static).update(self.snapshot.title or self.screen_title())
        self.query_one("#screen-subtitle", Static).update(self.subtitle_text())
        banner = self.query_one("#screen-banner", Static)
        banner_text = self.banner_text()
        banner.update(banner_text)
        banner.set_class(not bool(banner_text.strip()), "hidden")
        self.query_one("#screen-meta", Static).update(self.meta_text())
        section_title = f"内容流 · {len(self.snapshot.videos)} 条结果"
        if self.ALLOW_PAGING:
            section_title += f" · 第 {self.page} 页"
        self.query_one("#feed-section-title", Static).update(section_title)
        self.query_one("#feed-section-hint", Static).update(
            "j/k 移动 · Enter 详情 · c 评论 · o 浏览器 · f 收藏 · a/x 音频"
        )

    def _refresh_preview(self, video) -> None:
        detail = self.query_one("#detail-summary", Static)
        comments = self.query_one(CommentView)
        if video is None:
            detail.update(self.snapshot.empty_message)
            comments.set_comments([], title="评论预览", empty_message="当前没有可展示的视频")
            return

        cache_key = self._video_key(video)
        cached = self.detail_cache.get(cache_key)
        if cached is not None:
            title, lines, comment_items, comment_error = cached
            detail.update("\n".join(lines))
            empty_message = comment_error or self.comment_empty_message(video)
            comments.set_comments(comment_items, title=title, empty_message=empty_message)
            return

        star = "★ " if video.favorite else ""
        lines = [
            f"{star}{video.title}",
            f"UP主: {video.author}",
            f"播放: {video.play_label} · 时长: {video.duration}",
            f"发布: {video.published_label}",
            f"稿件: {video.ref_label}",
            "",
            video.stat_line or "暂无统计信息",
            "",
            video.description or "暂无简介",
        ]
        detail.update("\n".join(lines))
        comments.set_comments([], title="评论预览", empty_message=self.comment_empty_message(video))

    def comment_empty_message(self, video) -> str:
        if video is None:
            return "当前没有可展示的视频"
        if video.bvid or video.aid is not None:
            return "按 c 加载评论预览"
        return "当前条目暂不支持评论预览，请按 o 在浏览器查看"

    def _update_help_overlay(self) -> None:
        recent = " / ".join(self.adapter.recent_keywords(5)) or "暂无"
        overlay = self.query_one("#help-overlay", Static)
        overlay.update(f"{help_text()}\n\n最近搜索: {recent}")

    def _video_key(self, video) -> str:
        return video.bvid or (f"av{video.aid}" if video.aid is not None else video.url)

    @on(VideoList.VideoFocused)
    def _handle_video_focused(self, event: VideoList.VideoFocused) -> None:
        self._refresh_preview(event.video)

    @on(VideoList.VideoActivated)
    def _handle_video_activated(self, event: VideoList.VideoActivated) -> None:
        self.show_detail()

    def move_selection(self, delta: int) -> None:
        self.query_one(VideoList).move_selection(delta)
        self.focus_video_list()

    def show_detail(self) -> None:
        video = self.current_video()
        if video is None:
            self.set_status("当前没有可查看的视频")
            return
        self._detail_return_key = self._video_key(video)
        from .detail import DetailScreen

        self.app.push_screen(
            DetailScreen(adapter=self.adapter, video=video, initial_audio=self.app.audio_status),
            self._on_detail_closed,
        )

    def _on_detail_closed(self, should_refresh: bool | None) -> None:
        if should_refresh:
            self.load_feed(preserve_key=self._detail_return_key, set_status=False)
            self.set_status("已同步详情页的最新状态")
        else:
            self._refresh_preview(self.current_video())

    def go_back(self) -> None:
        if self.help_visible:
            self.toggle_help()
            return
        if len(self.app.screen_stack) > 1:
            self.app.pop_screen()
        else:
            self.set_status("已经在首页了")

    def focus_search(self) -> None:
        self.app.open_search()

    def next_channel(self) -> None:
        self.app.activate_home_channel((self.channel_index + 1) % len(self.adapter.channels))

    def prev_channel(self) -> None:
        self.app.activate_home_channel((self.channel_index - 1) % len(self.adapter.channels))

    def select_channel_shortcut(self, digit: str) -> None:
        index = channel_shortcut_index_from_key(ord(digit), len(self.adapter.channels))
        if index is not None:
            self.app.activate_home_channel(index)

    def rerun_last_search(self) -> None:
        keywords = self.adapter.recent_keywords(1)
        if not keywords:
            self.set_status("没有最近搜索记录")
            return
        self.app.open_search(keyword=keywords[0])

    def default_search(self) -> None:
        try:
            keyword = self.adapter.default_search_keyword()
        except BilibiliAPIError as exc:
            self.set_status(f"默认搜索词加载失败: {exc}")
            return
        if not keyword:
            self.set_status("当前没有默认搜索词")
            return
        self.app.open_search(keyword=keyword)

    def go_home(self) -> None:
        self.app.return_home()

    def show_history(self) -> None:
        self.app.open_history()

    def show_favorites(self) -> None:
        self.app.open_favorites()

    def toggle_favorite(self) -> None:
        video = self.current_video()
        if video is None:
            self.set_status("当前没有可收藏的视频")
            return
        try:
            added = self.adapter.toggle_favorite(video)
        except BilibiliAPIError as exc:
            self.set_status(str(exc))
            return
        message = f"{'已收藏' if added else '已取消收藏'}: {video.title}"
        self.load_feed(preserve_key=self._video_key(video), set_status=False)
        self.set_status(message)

    def toggle_audio(self) -> None:
        status = self.adapter.toggle_audio(self.current_video())
        self.app.update_audio_status(status)
        self.apply_audio_status(status)
        self.set_status(status.status_message)

    def stop_audio(self) -> None:
        status = self.adapter.stop_audio()
        self.app.update_audio_status(status)
        self.apply_audio_status(status)
        self.set_status(status.status_message)

    def next_page(self) -> None:
        if not self.ALLOW_PAGING:
            self.set_status("当前列表没有分页")
            return
        self.page += 1
        self.load_feed(set_status=False)
        self.set_status(f"已切到第 {self.page} 页")

    def prev_page(self) -> None:
        if not self.ALLOW_PAGING:
            self.set_status("当前列表没有分页")
            return
        if self.page <= 1:
            self.set_status("已经是第一页")
            return
        self.page -= 1
        self.load_feed(set_status=False)
        self.set_status(f"已切到第 {self.page} 页")

    def detail_page_up(self) -> None:
        self.set_status("当前页面没有详情滚动区域")

    def detail_page_down(self) -> None:
        self.set_status("当前页面没有详情滚动区域")

    def open_in_browser(self) -> None:
        video = self.current_video()
        if video is None:
            self.set_status("当前没有可打开的视频")
            return
        if video.item is not None:
            self.adapter.history_store.add_video(video.item)
        webbrowser.open(video.url)
        self.set_status(f"已打开: {video.url}")

    def refresh_comments(self) -> None:
        video = self.current_video()
        if video is None:
            self.set_status("当前没有可加载评论的视频")
            return
        try:
            detail = self.adapter.detail(video, comment_limit=4)
        except BilibiliAPIError as exc:
            self.set_status(f"评论加载失败: {exc}")
            return
        detail_video = detail.video or video
        cache_key = self._video_key(detail_video)
        preview_lines = list(detail.lines[:14]) if detail.lines else [detail_video.title]
        self.detail_cache[cache_key] = (
            "评论预览",
            preview_lines,
            list(detail.comments),
            detail.comments_error,
        )
        self._refresh_preview(detail_video)
        if detail.comments_error and not detail.comments:
            self.set_status(f"评论加载失败: {detail.comments_error}")
        else:
            self.set_status(f"已加载评论 {len(detail.comments)} 条")

    def refresh_view(self) -> None:
        self.load_feed(set_status=False)
        self.set_status(f"已刷新: {self.snapshot.title}")

    def toggle_help(self) -> None:
        self.help_visible = not self.help_visible
        overlay = self.query_one("#help-overlay", Static)
        overlay.set_class(not self.help_visible, "hidden")
        self.set_status("帮助浮层已打开" if self.help_visible else "帮助浮层已关闭")

    def _channel_label(self, index: int) -> str:
        channel = self.adapter.channels[index]
        shortcut = str(index + 1) if index < 9 else "0"
        return f"{shortcut}. {channel.label}"


class HomeScreen(BaseFeedScreen):
    MODE_KIND = "home"
    SHOW_SIDEBAR = True
    SHOW_SEARCH = False
    ALLOW_PAGING = True

    def screen_title(self) -> str:
        channel = self.adapter.channels[self.channel_index]
        return f"{channel.label} · 第 {self.page} 页"

    def subtitle_text(self) -> str:
        return "首页推荐流 · 热门 / 动画 / 游戏 / 音乐 / 番剧 · Tab / Shift+Tab 切换分区 · 1-9 / 0 直选"

    def banner_text(self) -> str:
        current = self.adapter.channels[self.channel_index].label
        hot_words = " / ".join(self.adapter.trending_keywords(4)) or "暂无"
        return f"  首页精选  ·  当前分区：{current}  ·  热门关键词：{hot_words}  "

    def meta_text(self) -> str:
        recent = " / ".join(self.adapter.recent_keywords(3)) or "暂无"
        return f"当前分区: {self.adapter.channels[self.channel_index].label} · 最近搜索: {recent}"

    def fetch_snapshot(self) -> FeedSnapshot:
        return self.adapter.load_home(channel_index=self.channel_index, page=self.page, page_size=self.PAGE_SIZE)

    @on(ListView.Highlighted, "#channel-list")
    def _handle_channel_highlighted(self, event: ListView.Highlighted) -> None:
        if event.list_view.index is None:
            return
        if event.list_view.index == self.channel_index:
            return
        self.set_channel(event.list_view.index)

    def set_channel(self, index: int) -> None:
        self.channel_index = max(0, min(index, len(self.adapter.channels) - 1))
        self.page = 1
        channel_list = self.query_one("#channel-list", ListView)
        if channel_list.index != self.channel_index:
            channel_list.index = self.channel_index
        self.load_feed(set_status=False)
        self.set_status(f"已切换到 {self.adapter.channels[self.channel_index].label}")
        self.focus_video_list()

    def focus_search(self) -> None:
        self.app.open_search()

    def next_channel(self) -> None:
        self.set_channel((self.channel_index + 1) % len(self.adapter.channels))

    def prev_channel(self) -> None:
        self.set_channel((self.channel_index - 1) % len(self.adapter.channels))

    def select_channel_shortcut(self, digit: str) -> None:
        index = channel_shortcut_index_from_key(ord(digit), len(self.adapter.channels))
        if index is not None:
            self.set_channel(index)

    def go_back(self) -> None:
        if self.help_visible:
            self.toggle_help()
            return
        self.set_status("已经在首页了")
