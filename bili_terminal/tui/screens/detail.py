from __future__ import annotations

from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Footer, Header, Static


class DetailScreen(Screen[None]):
    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield Static("DetailScreen 占位：阶段 2 迁移详情页、评论预览与 PgUp/PgDn 滚动。")
        yield Footer()
