from __future__ import annotations

from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Footer, Header, Static


class FavoritesScreen(Screen[None]):
    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield Static("FavoritesScreen 占位：阶段 3 接入 HistoryStore.get_favorite_videos()。")
        yield Footer()
