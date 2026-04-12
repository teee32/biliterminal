from __future__ import annotations

import webbrowser

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Footer, Header, Static

from ...bilibili_cli import BilibiliAPIError
from ..utils import AudioStatus, CommentSummary, DetailSnapshot, TextualAdapter, VideoSummary, help_text
from ..widgets import AudioBar, CommentView


class DetailScreen(Screen[bool]):
    def __init__(
        self,
        *,
        adapter: TextualAdapter,
        video: VideoSummary,
        initial_audio: AudioStatus | None = None,
    ) -> None:
        super().__init__()
        self.adapter = adapter
        self.video = video
        self.initial_audio = initial_audio or adapter.current_audio_status()
        self.status_text = "正在加载详情…"
        self.help_visible = False
        self.should_refresh_parent = False
        self.detail_snapshot = DetailSnapshot(video=video, lines=(video.title,), comments=(), favorite=video.favorite)

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Vertical(id="page-shell"):
            with Vertical(id="detail-hero-card", classes="surface-card"):
                yield Static("", id="detail-title")
                yield Static("", id="detail-meta")
            with Horizontal(id="detail-layout"):
                with Vertical(id="detail-main-pane", classes="panel-main"):
                    yield Static("视频详情", classes="panel-title")
                    with VerticalScroll(id="detail-scroll", classes="surface-card"):
                        yield Static("", id="detail-lines")
                with Vertical(id="detail-side-pane", classes="panel panel-side"):
                    yield Static("互动区", classes="panel-title")
                    yield Static("j/k 滚动 · PgUp/PgDn 翻页 · a/x 音频 · f 收藏 · c 评论 · b 返回", id="detail-hint")
                    yield CommentView(id="comment-view", classes="surface-card")
        yield Static("", id="status-line")
        yield AudioBar(id="audio-bar")
        yield Static(help_text(), id="help-overlay", classes="hidden")
        yield Footer()

    def on_mount(self) -> None:
        if hasattr(self.app, "apply_theme_to_screen"):
            self.app.apply_theme_to_screen(self)
        self.apply_audio_status(self.initial_audio)
        self._load_detail(set_status=False)
        self.query_one("#detail-scroll", VerticalScroll).focus()

    def apply_audio_status(self, status: AudioStatus) -> None:
        self.query_one(AudioBar).set_audio_status(status)

    def set_status(self, message: str) -> None:
        self.status_text = message
        self.query_one("#status-line", Static).update(f"状态：{message}")

    def _render_detail(self) -> None:
        current = self.detail_snapshot.video or self.video
        star = "★ " if self.detail_snapshot.favorite else ""
        self.query_one("#detail-title", Static).update(f"{star}{current.title}")
        self.query_one("#detail-meta", Static).update(
            f"UP主 {current.author}  ·  播放 {current.play_label}  ·  发布 {current.published_label}  ·  稿件 {current.ref_label}"
        )
        self.query_one("#detail-lines", Static).update("\n".join(self.detail_snapshot.lines))
        comment_title = "评论预览"
        empty_message = self.detail_snapshot.comments_error or "按 c 刷新评论预览"
        self.query_one(CommentView).set_comments(
            list(self.detail_snapshot.comments),
            title=comment_title,
            empty_message=empty_message,
        )

    def _load_detail(self, *, set_status: bool = True) -> None:
        try:
            self.detail_snapshot = self.adapter.detail(self.video, comment_limit=4)
            current = self.detail_snapshot.video or self.video
            if self.detail_snapshot.video is not None:
                self.video = self.detail_snapshot.video
            self._render_detail()
            if set_status:
                if self.detail_snapshot.comments_error and not self.detail_snapshot.comments:
                    self.set_status(f"评论加载失败: {self.detail_snapshot.comments_error}")
                else:
                    self.set_status(f"已加载详情: {current.title}")
        except BilibiliAPIError as exc:
            self.set_status(f"详情加载失败: {exc}")
            self.detail_snapshot = DetailSnapshot(
                video=self.video,
                lines=(self.video.title, str(exc)),
                comments=(),
                favorite=self.video.favorite,
                comments_error=str(exc),
            )
            self._render_detail()

    def move_selection(self, delta: int) -> None:
        self.query_one("#detail-scroll", VerticalScroll).scroll_relative(y=delta)

    def show_detail(self) -> None:
        return None

    def go_back(self) -> None:
        if self.help_visible:
            self.toggle_help()
            return
        self.dismiss(self.should_refresh_parent)

    def toggle_favorite(self) -> None:
        try:
            is_added = self.adapter.toggle_favorite(self.video)
        except BilibiliAPIError as exc:
            self.set_status(str(exc))
            return
        self.should_refresh_parent = True
        self._load_detail(set_status=False)
        self.set_status(f"{'已收藏' if is_added else '已取消收藏'}: {self.video.title}")

    def toggle_audio(self) -> None:
        status = self.adapter.toggle_audio(self.video)
        self.app.update_audio_status(status)
        self.apply_audio_status(status)
        self.set_status(status.status_message)

    def stop_audio(self) -> None:
        status = self.adapter.stop_audio()
        self.app.update_audio_status(status)
        self.apply_audio_status(status)
        self.set_status(status.status_message)

    def detail_page_up(self) -> None:
        self.query_one("#detail-scroll", VerticalScroll).scroll_page_up()

    def detail_page_down(self) -> None:
        self.query_one("#detail-scroll", VerticalScroll).scroll_page_down()

    def open_in_browser(self) -> None:
        if self.video.item is not None:
            self.adapter.history_store.add_video(self.video.item)
        webbrowser.open(self.video.url)
        self.set_status(f"已打开: {self.video.url}")

    def refresh_comments(self) -> None:
        try:
            comments = list(self.adapter.comments(self.video, page_size=4))
        except BilibiliAPIError as exc:
            self.detail_snapshot = DetailSnapshot(
                video=self.video,
                lines=self.detail_snapshot.lines,
                comments=(),
                favorite=self.detail_snapshot.favorite,
                comments_error=str(exc),
            )
            self._render_detail()
            self.set_status(f"评论加载失败: {exc}")
            return
        self.detail_snapshot = DetailSnapshot(
            video=self.detail_snapshot.video or self.video,
            lines=self.detail_snapshot.lines,
            comments=tuple(comments),
            favorite=self.detail_snapshot.favorite,
            comments_error=None,
        )
        self._render_detail()
        self.set_status(f"已加载评论 {len(comments)} 条")

    def refresh_view(self) -> None:
        self._load_detail(set_status=False)
        self.set_status(f"已刷新详情: {self.video.title}")

    def toggle_help(self) -> None:
        self.help_visible = not self.help_visible
        overlay = self.query_one("#help-overlay", Static)
        overlay.set_class(not self.help_visible, "hidden")
        self.set_status("帮助浮层已打开" if self.help_visible else "帮助浮层已关闭")
