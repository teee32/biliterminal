from __future__ import annotations

from ..utils import FeedSnapshot, TextualAdapter
from .home import BaseFeedScreen


class FavoritesScreen(BaseFeedScreen):
    MODE_KIND = "favorites"
    SHOW_SEARCH = False
    ALLOW_PAGING = False

    def __init__(self, *, adapter: TextualAdapter, initial_audio=None) -> None:
        super().__init__(adapter=adapter, initial_audio=initial_audio)

    def subtitle_text(self) -> str:
        return "收藏夹 · f 取消收藏 · Enter 查看详情 · o 浏览器打开"

    def meta_text(self) -> str:
        return f"共 {len(self.snapshot.videos)} 条收藏"

    def fetch_snapshot(self) -> FeedSnapshot:
        return self.adapter.favorites()
