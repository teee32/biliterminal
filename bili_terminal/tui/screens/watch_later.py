from __future__ import annotations

from ...core import BilibiliAPIError
from ..keymap import WATCH_LATER_FEED_HINT_TEXT, WATCH_LATER_SUBTITLE_TEXT
from ..utils import FeedSnapshot, TextualAdapter, format_no_video_status
from .home import BaseFeedScreen


class WatchLaterScreen(BaseFeedScreen):
    MODE_KIND = "watch_later"
    SHOW_SEARCH = False
    ALLOW_PAGING = False

    def __init__(self, *, adapter: TextualAdapter, initial_audio=None) -> None:
        super().__init__(adapter=adapter, initial_audio=initial_audio)

    def subtitle_text(self) -> str:
        return WATCH_LATER_SUBTITLE_TEXT

    def meta_text(self) -> str:
        return f"共 {len(self.snapshot.videos)} 条稍后看"

    def feed_hint_text(self) -> str:
        return WATCH_LATER_FEED_HINT_TEXT

    def banner_text(self) -> str:
        return "  稍后看队列  ·  手动加入，本地持久化  "

    def fetch_snapshot(self) -> FeedSnapshot:
        return self.adapter.watch_later()

    def toggle_watch_later(self) -> None:
        video = self.current_video()
        if video is None:
            self.set_status(format_no_video_status("移出稍后看"))
            return
        try:
            removed = self.adapter.remove_watch_later(video)
        except BilibiliAPIError as exc:
            self.set_status(str(exc))
            return
        title = video.title
        self.load_feed(set_status=False)
        self.set_status(f"{'已移出稍后看' if removed else '稍后看中未找到'}: {title}")
