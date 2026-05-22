from __future__ import annotations

from ..keymap import HISTORY_SUBTITLE_TEXT
from ..utils import FeedSnapshot, TextualAdapter
from .home import BaseFeedScreen


class HistoryScreen(BaseFeedScreen):
    MODE_KIND = "history"
    SHOW_SEARCH = False
    ALLOW_PAGING = False

    def __init__(self, *, adapter: TextualAdapter, initial_audio=None) -> None:
        super().__init__(adapter=adapter, initial_audio=initial_audio)

    def subtitle_text(self) -> str:
        return HISTORY_SUBTITLE_TEXT

    def meta_text(self) -> str:
        return f"共 {len(self.snapshot.videos)} 条最近浏览记录"

    def fetch_snapshot(self) -> FeedSnapshot:
        return self.adapter.history(limit=20)
