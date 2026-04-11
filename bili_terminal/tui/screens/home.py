from __future__ import annotations

import webbrowser

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Footer, Header, Input, ListItem, ListView, Static

from ...bilibili_cli import BilibiliClient, HistoryStore, channel_shortcut_index_from_key
from ..utils import (
    DEFAULT_SEARCH_PLACEHOLDER,
    DEFAULT_STATUS_TEXT,
    ChannelSpec,
    VideoSummary,
    default_channels,
    help_text,
    placeholder_comments,
    placeholder_videos,
)
from ..widgets import AudioBar, CommentView, VideoList


class HomeScreen(Screen[None]):
    """Stage-1 Home screen for the future Textual migration."""

    def __init__(
        self,
        *,
        client: BilibiliClient | None = None,
        history_store: HistoryStore | None = None,
    ) -> None:
        super().__init__()
        self.client = client
        self.history_store = history_store
        self.channels: list[ChannelSpec] = default_channels()
        self.channel_index = 0
        self.mode = "home"
        self.status_text = DEFAULT_STATUS_TEXT
        self.help_visible = False
        self._videos = placeholder_videos(self.channels[0].label)

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Horizontal(id="home-layout"):
            with Vertical(id="sidebar-pane", classes="panel"):
                yield Static("分区 / Channels", classes="panel-title")
                yield ListView(
                    *(ListItem(Static(self._channel_label(index, channel), classes="channel-item")) for index, channel in enumerate(self.channels)),
                    id="channel-list",
                )
            with Vertical(id="main-pane", classes="panel"):
                yield Static("BiliTerminal · Textual v0.3.0 阶段 1", id="hero-title")
                yield Static("HomeScreen / VideoList / AudioBar 架构骨架（保留原快捷键语义）", id="hero-subtitle")
                yield Input(placeholder=DEFAULT_SEARCH_PLACEHOLDER, id="search-input")
                yield Static("", id="mode-banner")
                yield VideoList(self._videos, id="video-list")
            with Vertical(id="detail-pane", classes="panel"):
                yield Static("", id="detail-summary")
                yield CommentView(id="comment-view")
        yield Static("", id="status-line")
        yield AudioBar(id="audio-bar")
        yield Static(help_text(), id="help-overlay", classes="hidden")
        yield Footer()

    def on_mount(self) -> None:
        channel_list = self.query_one("#channel-list", ListView)
        channel_list.index = self.channel_index
        self.query_one(VideoList).set_videos(self._videos)
        self.query_one(VideoList).focus()
        self._sync_screen()

    @on(ListView.Highlighted, "#channel-list")
    def _handle_channel_highlighted(self, event: ListView.Highlighted) -> None:
        if event.list_view.id == "channel-list" and event.list_view.index is not None:
            self._set_channel(event.list_view.index, from_shortcut=False)

    @on(VideoList.VideoFocused)
    def _handle_video_focused(self, event: VideoList.VideoFocused) -> None:
        self._update_detail(event.video)

    @on(VideoList.VideoActivated)
    def _handle_video_activated(self, event: VideoList.VideoActivated) -> None:
        self.show_detail()
        self._update_detail(event.video)

    @on(Input.Changed, "#search-input")
    def _handle_search_changed(self, event: Input.Changed) -> None:
        value = event.value.strip()
        if value:
            self.status_text = f"搜索输入中：{value}（阶段 1 暂不发起真实请求）"
        else:
            self.status_text = DEFAULT_STATUS_TEXT
        self._sync_status_only()

    def move_selection(self, delta: int) -> None:
        self.query_one(VideoList).move_selection(delta)
        self.query_one(VideoList).focus()

    def show_detail(self) -> None:
        video = self.query_one(VideoList).selected_video
        title = video.title if video is not None else "当前条目"
        self.mode = "detail"
        self.status_text = f"详情占位：{title}；阶段 2 将接入真正的 DetailScreen。"
        self._sync_screen()

    def go_back(self) -> None:
        self.mode = "home"
        self.status_text = f"已返回首页骨架：{self.channels[self.channel_index].label}"
        self._sync_screen()

    def focus_search(self) -> None:
        self.mode = "search"
        self.query_one("#search-input", Input).focus()
        self.status_text = "搜索框已聚焦；支持中文实时输入，阶段 2 接真实搜索接口。"
        self._sync_screen()

    def next_channel(self) -> None:
        self._set_channel((self.channel_index + 1) % len(self.channels), from_shortcut=False)

    def prev_channel(self) -> None:
        self._set_channel((self.channel_index - 1) % len(self.channels), from_shortcut=False)

    def select_channel_shortcut(self, digit: str) -> None:
        index = channel_shortcut_index_from_key(ord(digit), len(self.channels))
        if index is not None:
            self._set_channel(index, from_shortcut=True)

    def rerun_last_search(self) -> None:
        self.mode = "search"
        self.query_one("#search-input", Input).value = "最近一次搜索（阶段 1 占位）"
        self.status_text = "最近一次搜索占位：阶段 2 复用 HistoryStore.get_recent_keywords()。"
        self._sync_screen()

    def default_search(self) -> None:
        self.mode = "search"
        self.query_one("#search-input", Input).value = "默认搜索词（阶段 1 占位）"
        self.status_text = "默认搜索词占位：阶段 2 复用现有 search_default()。"
        self._sync_screen()

    def go_home(self) -> None:
        self.mode = "home"
        self.status_text = f"已切回首页流占位：{self.channels[self.channel_index].label}"
        self._sync_screen()

    def show_history(self) -> None:
        self.mode = "history"
        self.status_text = "历史记录占位：阶段 2 直接复用 HistoryStore.get_recent_videos()。"
        self._sync_screen()

    def show_favorites(self) -> None:
        self.mode = "favorites"
        self.status_text = "收藏夹占位：阶段 2 直接复用 HistoryStore.get_favorite_videos()。"
        self._sync_screen()

    def toggle_favorite(self) -> None:
        video = self.query_one(VideoList).selected_video
        title = video.title if video is not None else "当前条目"
        self.status_text = f"收藏操作占位：{title}；阶段 2 会调用 HistoryStore.toggle_favorite()。"
        self._sync_status_only()

    def toggle_audio(self) -> None:
        video = self.query_one(VideoList).selected_video
        bar = self.query_one(AudioBar)
        if video is None:
            bar.set_status("当前没有可播放的占位视频")
        else:
            bar.set_track(video.title, state="playing")
            bar.set_status("阶段 1 仅保留全局 AudioBar；阶段 2 接现有音频播放链路。")
        self.status_text = "音频控制占位：a 语义已保留。"
        self._sync_status_only()

    def stop_audio(self) -> None:
        self.query_one(AudioBar).stop()
        self.query_one(AudioBar).set_status("音频停止占位：阶段 2 接 stop_audio_playback()。")
        self.status_text = "音频停止占位：x 语义已保留。"
        self._sync_status_only()

    def next_page(self) -> None:
        self.status_text = "下一页占位：阶段 2 接列表分页与真实翻页状态。"
        self._sync_status_only()

    def prev_page(self) -> None:
        self.status_text = "上一页占位：阶段 2 接列表分页与真实翻页状态。"
        self._sync_status_only()

    def detail_page_up(self) -> None:
        self.status_text = "详情滚动占位：PgUp 已保留。"
        self._sync_status_only()

    def detail_page_down(self) -> None:
        self.status_text = "详情滚动占位：PgDn 已保留。"
        self._sync_status_only()

    def open_in_browser(self) -> None:
        video = self.query_one(VideoList).selected_video
        if video is None:
            self.status_text = "当前没有可打开的占位视频。"
        else:
            webbrowser.open(video.url)
            self.status_text = f"已打开占位链接：{video.url}"
        self._sync_status_only()

    def refresh_comments(self) -> None:
        video = self.query_one(VideoList).selected_video
        self.query_one(CommentView).set_comments(placeholder_comments(video), title="评论预览 / CommentView")
        self.status_text = "评论区骨架已刷新；阶段 2 将接真实热评数据。"
        self._sync_status_only()

    def refresh_view(self) -> None:
        self._videos = placeholder_videos(self.channels[self.channel_index].label)
        self.query_one(VideoList).set_videos(self._videos)
        self.status_text = f"已刷新占位列表：{self.channels[self.channel_index].label}"
        self._sync_screen()

    def toggle_help(self) -> None:
        self.help_visible = not self.help_visible
        help_overlay = self.query_one("#help-overlay", Static)
        help_overlay.set_class(not self.help_visible, "hidden")
        self.status_text = "帮助浮层已打开。" if self.help_visible else "帮助浮层已关闭。"
        self._sync_status_only()

    def _set_channel(self, index: int, *, from_shortcut: bool) -> None:
        if not (0 <= index < len(self.channels)):
            return
        self.channel_index = index
        channel_list = self.query_one("#channel-list", ListView)
        if channel_list.index != index:
            channel_list.index = index
        self._videos = placeholder_videos(self.channels[index].label)
        self.query_one(VideoList).set_videos(self._videos)
        prefix = "已直达" if from_shortcut else "已切换到"
        self.mode = "home"
        self.status_text = f"{prefix}占位分区：{self.channels[index].label}"
        self._sync_screen()

    def _sync_screen(self) -> None:
        self.query_one("#mode-banner", Static).update(self._mode_banner())
        self._update_detail(self.query_one(VideoList).selected_video)
        self._sync_status_only()

    def _sync_status_only(self) -> None:
        self.query_one("#status-line", Static).update(f"状态：{self.status_text}")

    def _update_detail(self, video: VideoSummary | None) -> None:
        detail = self.query_one("#detail-summary", Static)
        comments = self.query_one(CommentView)
        if video is None:
            detail.update("详情区占位：当前没有选中视频。")
            comments.set_comments([], title="评论预览 / CommentView")
            return
        detail.update(
            "\n".join(
                [
                    f"当前分区：{self.channels[self.channel_index].label}",
                    f"标题：{video.title}",
                    f"作者：{video.author}",
                    f"时长：{video.duration}",
                    f"播放：{video.play_label}",
                    "",
                    "阶段 1：这里保留详情 / 评论 / 音频 / 收藏联动的位置。",
                ]
            )
        )
        comments.set_comments(placeholder_comments(video), title="评论预览 / CommentView")

    def _channel_label(self, index: int, channel: ChannelSpec) -> str:
        shortcut = str(index + 1) if index < 9 else "0"
        return f"{shortcut}. {channel.label}"

    def _mode_banner(self) -> str:
        return {
            "home": "HomeScreen：分区 Sidebar + VideoList + 详情/评论占位 + AudioBar",
            "search": "Search 占位：保留 / / s / l / d 语义，阶段 2 接真实搜索流",
            "detail": "Detail 占位：保留 Enter / Esc / b / PgUp / PgDn 语义",
            "history": "History 占位：保留 v 快捷键与最近浏览视图",
            "favorites": "Favorites 占位：保留 m / f 快捷键与收藏视图",
        }.get(self.mode, "Textual 阶段 1 骨架")
