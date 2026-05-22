from __future__ import annotations

from textual import on
from textual.widgets import Input

from ..keymap import SEARCH_EMPTY_PROMPT_TEXT, SEARCH_SUBTITLE_TEXT
from ..utils import (
    DEFAULT_DEFAULT_SEARCH_LOAD_FAILED_PREFIX,
    DEFAULT_NO_DEFAULT_SEARCH_STATUS,
    DEFAULT_NO_RECENT_SEARCH_STATUS,
    FeedSnapshot,
    TextualAdapter,
    format_search_title,
    format_recent_searches_text,
)
from .home import BaseFeedScreen


class SearchScreen(BaseFeedScreen):
    MODE_KIND = "search"
    SHOW_SEARCH = True
    ALLOW_PAGING = True

    def __init__(self, *, adapter: TextualAdapter, initial_audio=None, keyword: str = "", page: int = 1) -> None:
        super().__init__(adapter=adapter, initial_audio=initial_audio, keyword=keyword, page=page)

    def screen_title(self) -> str:
        if self.keyword:
            return format_search_title(self.keyword, self.page)
        return "搜索"

    def subtitle_text(self) -> str:
        return SEARCH_SUBTITLE_TEXT

    def meta_text(self) -> str:
        return format_recent_searches_text(self.adapter.recent_keywords(5))

    def fetch_snapshot(self) -> FeedSnapshot:
        if not self.keyword.strip():
            return self.make_empty_snapshot(SEARCH_EMPTY_PROMPT_TEXT)
        return self.adapter.search(self.keyword, page=self.page, page_size=self.PAGE_SIZE)

    def on_mount(self) -> None:
        super().on_mount()
        input_widget = self.query_one(Input)
        input_widget.value = self.keyword
        if not self.keyword:
            input_widget.focus()

    @on(Input.Changed, "#search-input")
    def _handle_search_changed(self, event: Input.Changed) -> None:
        value = event.value.strip()
        if value:
            self.set_status(f"搜索输入中：{value}")

    @on(Input.Submitted, "#search-input")
    def _handle_search_submitted(self, event: Input.Submitted) -> None:
        self.execute_search(event.value)

    def execute_search(self, keyword: str) -> None:
        cleaned = keyword.strip()
        if not cleaned:
            self.keyword = ""
            self.snapshot = self.make_empty_snapshot(SEARCH_EMPTY_PROMPT_TEXT)
            self.query_one(Input).value = ""
            self.load_feed(set_status=False)
            self.set_status("请输入有效关键词")
            return
        self.keyword = cleaned
        self.page = 1
        self.query_one(Input).value = cleaned
        self.load_feed(set_status=False)
        self.set_status(f"搜索完成：{cleaned}")
        self.focus_video_list()

    def focus_search(self) -> None:
        self.query_one(Input).focus()

    def show_detail(self) -> None:
        if self.query_one(Input).has_focus:
            self.execute_search(self.query_one(Input).value)
            return
        super().show_detail()

    def rerun_last_search(self) -> None:
        keywords = self.adapter.recent_keywords(1)
        if not keywords:
            self.set_status(DEFAULT_NO_RECENT_SEARCH_STATUS)
            return
        self.execute_search(keywords[0])

    def default_search(self) -> None:
        try:
            keyword = self.adapter.default_search_keyword()
        except Exception as exc:
            self.set_status(f"{DEFAULT_DEFAULT_SEARCH_LOAD_FAILED_PREFIX} {exc}")
            return
        if not keyword:
            self.set_status(DEFAULT_NO_DEFAULT_SEARCH_STATUS)
            return
        self.execute_search(keyword)

    def refresh_view(self) -> None:
        if not self.keyword:
            self.set_status("当前没有可刷新的搜索关键词")
            return
        self.load_feed(set_status=False)
        self.set_status(f"已刷新搜索结果：{self.keyword}")
