from __future__ import annotations

from textual import on
from textual.message import Message
from textual.widgets import ListItem, ListView, Static

from ..utils import VideoSummary

try:  # pragma: no cover - best-effort feature probe
    from textual_image.widget import Image as _TextualImageWidget  # noqa: F401
except Exception:  # pragma: no cover - textual-image is optional at import time
    _HAS_TEXTUAL_IMAGE = False
else:  # pragma: no cover - exercised only when dependency is installed
    _HAS_TEXTUAL_IMAGE = True

IMAGE_SUPPORT_NOTE = "封面层预留 textual-image（Kitty / iTerm2 / Sixel）；阶段 2 接真实 cover URL。"


class VideoList(ListView):
    """Keyboard- and mouse-friendly video list placeholder."""

    class VideoFocused(Message):
        def __init__(self, video: VideoSummary) -> None:
            self.video = video
            super().__init__()

    class VideoActivated(Message):
        def __init__(self, video: VideoSummary) -> None:
            self.video = video
            super().__init__()

    def __init__(self, videos: list[VideoSummary] | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self._videos: list[VideoSummary] = list(videos or [])

    def on_mount(self) -> None:
        self.set_videos(self._videos)

    def set_videos(self, videos: list[VideoSummary]) -> None:
        self._videos = list(videos)
        self.clear()
        self.extend(
            ListItem(Static(self._render_item(video), classes="video-list__item"))
            for video in self._videos
        )
        if self._videos:
            self.index = 0
            self.call_after_refresh(self._post_focused_video)

    @property
    def selected_video(self) -> VideoSummary | None:
        if not self._videos:
            return None
        if self.index is None:
            return self._videos[0]
        return self._videos[max(0, min(self.index, len(self._videos) - 1))]

    def move_selection(self, delta: int) -> None:
        if not self._videos:
            return
        current = self.index if self.index is not None else 0
        self.index = max(0, min(current + delta, len(self._videos) - 1))
        self._post_focused_video()

    @on(ListView.Highlighted)
    def _handle_highlighted(self, event: ListView.Highlighted) -> None:
        if event.list_view is self:
            self._post_focused_video()

    @on(ListView.Selected)
    def _handle_selected(self, event: ListView.Selected) -> None:
        if event.list_view is self:
            video = self.selected_video
            if video is not None:
                self.post_message(self.VideoActivated(video))

    def _post_focused_video(self) -> None:
        video = self.selected_video
        if video is not None:
            self.post_message(self.VideoFocused(video))

    def _render_item(self, video: VideoSummary) -> str:
        image_note = IMAGE_SUPPORT_NOTE if _HAS_TEXTUAL_IMAGE else "已预留封面位；安装 textual-image 后可继续接线。"
        return (
            f"{video.title}\n"
            f"{video.author} · {video.play_label} · {video.duration}\n"
            f"{video.description}\n"
            f"{image_note}"
        )
