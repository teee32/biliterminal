from __future__ import annotations

from ..utils import FeedSnapshot, TextualAdapter
from .home import BaseFeedScreen


class HistoryScreen(BaseFeedScreen):
    MODE_KIND = "history"
    SHOW_SEARCH = False
    ALLOW_PAGING = False

    def __init__(self, *, adapter: TextualAdapter, initial_audio=None) -> None:
        super().__init__(adapter=adapter, initial_audio=initial_audio)

    def subtitle_text(self) -> str:
        return "最近浏览 · Enter 查看详情 · o 浏览器打开 · a/x 控制音频"

    def meta_text(self) -> str:
        return f"共 {len(self.snapshot.videos)} 条最近浏览记录"

    def fetch_snapshot(self) -> FeedSnapshot:
        return self.adapter.history(limit=20)
