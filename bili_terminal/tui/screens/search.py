from __future__ import annotations

from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Footer, Header, Static


class SearchScreen(Screen[None]):
    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield Static("SearchScreen 占位：阶段 2 接入真实搜索结果流与中文实时输入。")
        yield Footer()
