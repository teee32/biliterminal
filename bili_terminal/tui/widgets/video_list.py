from __future__ import annotations

import textwrap

from textual import on
from textual.message import Message
from textual.widgets import ListItem, ListView, Static

from ..utils import VideoSummary


class VideoList(ListView):
    """Keyboard- and mouse-friendly video list used by the Textual UI."""

    class VideoFocused(Message):
        def __init__(self, video: VideoSummary, index: int) -> None:
            self.video = video
            self.index = index
            super().__init__()

    class VideoActivated(Message):
        def __init__(self, video: VideoSummary, index: int) -> None:
            self.video = video
            self.index = index
            super().__init__()

    def __init__(self, videos: list[VideoSummary] | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self._videos: list[VideoSummary] = list(videos or [])

    def on_mount(self) -> None:
        self.set_videos(self._videos)

    def on_resize(self) -> None:
        if not self._videos:
            return
        selected_index = self.index or 0
        self.set_videos(self._videos, selected_index=selected_index)

    @property
    def videos(self) -> list[VideoSummary]:
        return list(self._videos)

    def set_videos(self, videos: list[VideoSummary], *, selected_index: int = 0) -> None:
        self._videos = list(videos)
        self.clear()
        self.extend(ListItem(Static(self._render_item(video), classes="video-list__item")) for video in self._videos)
        if self._videos:
            self.index = max(0, min(selected_index, len(self._videos) - 1))
            self.call_after_refresh(self._post_focused_video)
        else:
            self.index = None

    @property
    def selected_video(self) -> VideoSummary | None:
        if not self._videos:
            return None
        if self.index is None:
            return self._videos[0]
        return self._videos[max(0, min(self.index, len(self._videos) - 1))]

    def selected_key(self) -> str | None:
        video = self.selected_video
        if video is None:
            return None
        if video.bvid:
            return video.bvid
        if video.aid is not None:
            return f"av{video.aid}"
        return video.url

    def move_selection(self, delta: int) -> None:
        if not self._videos:
            return
        current = self.index if self.index is not None else 0
        self.index = max(0, min(current + delta, len(self._videos) - 1))
        self._post_focused_video()

    def select_key(self, key: str | None) -> bool:
        if not key:
            return False
        for index, video in enumerate(self._videos):
            candidate = video.bvid or (f"av{video.aid}" if video.aid is not None else video.url)
            if candidate == key:
                self.index = index
                self._post_focused_video()
                return True
        return False

    @on(ListView.Highlighted)
    def _handle_highlighted(self, event: ListView.Highlighted) -> None:
        if event.list_view is self:
            self._post_focused_video()

    @on(ListView.Selected)
    def _handle_selected(self, event: ListView.Selected) -> None:
        if event.list_view is self:
            video = self.selected_video
            index = self.index if self.index is not None else 0
            if video is not None:
                self.post_message(self.VideoActivated(video, index))

    def _post_focused_video(self) -> None:
        video = self.selected_video
        index = self.index if self.index is not None else 0
        if video is not None:
            self.post_message(self.VideoFocused(video, index))

    def _render_item(self, video: VideoSummary) -> str:
        width = max(26, (self.size.width or 64) - 8)
        title = f"★ {video.title}" if video.favorite else video.title
        title_lines = self._wrap(title, width=width, max_lines=2)
        description = " ".join(video.description.split()) or "暂无简介"
        description_lines = self._wrap(description, width=width, max_lines=1)
        stat_line = video.stat_line or "暂无完整统计"
        ref_line = f"{video.ref_label}  ·  发布 {video.published_label}"
        return (
            f"{title_lines}\n"
            f"UP主 {video.author}  ·  {video.play_label} 播放  ·  时长 {video.duration}\n"
            f"{stat_line}\n"
            f"{ref_line}\n"
            f"{description_lines}"
        )

    def _wrap(self, value: str, *, width: int, max_lines: int) -> str:
        lines = textwrap.wrap(
            value,
            width=max(10, width),
            break_long_words=False,
            replace_whitespace=False,
            drop_whitespace=True,
        )
        if not lines:
            return ""
        if len(lines) <= max_lines:
            return "\n".join(lines)
        trimmed = lines[: max(1, max_lines)]
        last = trimmed[-1].rstrip(" .")
        trimmed[-1] = f"{last}…"
        return "\n".join(trimmed)
