from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.screen import Screen
from textual.widgets import Footer, Header, Static

from ..bilibili_cli import HOME_CHANNELS
from .widgets import KeymapLegend, PlaceholderPanel

HOME_CHANNEL_LABELS = [str(channel["label"]) for channel in HOME_CHANNELS]
PRIMARY_KEYMAP = [
    ("Tab", "切换分区"),
    ("1-0", "直选首页分区"),
    ("/", "搜索"),
    ("Enter", "详情"),
    ("a", "播放/暂停音频"),
    ("x", "停止音频"),
    ("f", "收藏"),
    ("m", "收藏夹"),
    ("v", "最近浏览"),
    ("b", "返回首页"),
]


class HomeScreen(Screen[None]):
    """Stage-1 home screen for the future Textual migration."""

    channel_index = reactive(0)
    mode = reactive("home")
    status = reactive("Textual phase-1 shell ready; next step is wiring the extracted core service layer.")

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield Static("BiliTerminal · Textual v0.3.0 phase-1", id="hero-title")
        yield Static(
            "保持现有 curses TUI 可用，同时为 HomeScreen、分区切换、历史/收藏与音频控制预留稳定挂点。",
            id="hero-subtitle",
        )
        yield Static("", id="channel-strip")
        with Horizontal(id="home-grid"):
            yield PlaceholderPanel(
                "今日精选 / Featured",
                [
                    "占位：推荐流首屏卡片。",
                    "未来接入 core.feed.get_home(channel='recommend')。",
                    "保留 Enter / o / a / f 的卡片级操作意图。",
                ],
                panel_id="featured-panel",
            )
            with Vertical(id="side-panels"):
                yield PlaceholderPanel(
                    "列表 / Shelf",
                    [
                        "占位：可切换 首页 / 搜索 / 历史 / 收藏。",
                        "未来接入 core.history 与 core.feed 的统一列表模型。",
                    ],
                    panel_id="shelf-panel",
                )
                yield PlaceholderPanel(
                    "详情 / 热评预览",
                    [
                        "占位：详情页摘要与评论侧栏。",
                        "未来复用 build_detail_lines 与 comments() 返回的数据模型。",
                    ],
                    panel_id="detail-panel",
                )
        yield KeymapLegend(PRIMARY_KEYMAP, legend_id="keymap-legend")
        yield Static("", id="status-line")
        yield Footer()

    def on_mount(self) -> None:
        self.call_after_refresh(self.refresh_screen)

    def refresh_screen(self) -> None:
        self.query_one("#channel-strip", Static).update(self._channel_summary())
        self.query_one("#status-line", Static).update(f"状态：{self.status}")
        self.query_one("#featured-panel", PlaceholderPanel).set_panel(body=self._featured_lines())
        self.query_one("#shelf-panel", PlaceholderPanel).set_panel(title=self._shelf_title(), body=self._shelf_lines())
        self.query_one("#detail-panel", PlaceholderPanel).set_panel(body=self._detail_lines())

    def cycle_channel(self, step: int) -> None:
        self.channel_index = (self.channel_index + step) % len(HOME_CHANNEL_LABELS)
        self.mode = "home"
        self.status = f"已切换到占位分区：{HOME_CHANNEL_LABELS[self.channel_index]}"
        self.refresh_screen()

    def direct_channel(self, digit: str) -> None:
        if digit == "0":
            index = 9
        else:
            index = int(digit) - 1
        if 0 <= index < len(HOME_CHANNEL_LABELS):
            self.channel_index = index
            self.mode = "home"
            self.status = f"已直达占位分区：{HOME_CHANNEL_LABELS[index]}"
            self.refresh_screen()

    def show_search_placeholder(self) -> None:
        self.mode = "search"
        self.status = "搜索框占位已激活；phase-2 接入关键字输入与搜索结果流。"
        self.refresh_screen()

    def show_detail_placeholder(self) -> None:
        self.mode = "detail"
        self.status = "详情页占位已激活；phase-2 复用 build_detail_lines/comments()。"
        self.refresh_screen()

    def show_history_placeholder(self) -> None:
        self.mode = "history"
        self.status = "最近浏览占位已激活；phase-2 直接接入 HistoryStore.get_recent_videos()。"
        self.refresh_screen()

    def show_favorites_placeholder(self) -> None:
        self.mode = "favorites"
        self.status = "收藏夹占位已激活；phase-2 直接接入 HistoryStore.get_favorite_videos()。"
        self.refresh_screen()

    def toggle_audio_placeholder(self) -> None:
        self.status = "音频控制占位：后续复用 play_audio_for_item()/toggle_audio_playback()。"
        self.refresh_screen()

    def stop_audio_placeholder(self) -> None:
        self.status = "停止音频占位：后续复用 stop_audio_playback()。"
        self.refresh_screen()

    def toggle_favorite_placeholder(self) -> None:
        self.status = "收藏操作占位：后续复用 HistoryStore.toggle_favorite()。"
        self.refresh_screen()

    def show_comments_placeholder(self) -> None:
        self.status = "评论刷新占位：后续复用 BilibiliClient.comments()。"
        self.refresh_screen()

    def rerun_last_search_placeholder(self) -> None:
        self.mode = "search"
        self.status = "最近一次搜索占位：phase-2 复用 HistoryStore.get_recent_keywords()。"
        self.refresh_screen()

    def refresh_placeholder(self) -> None:
        self.status = "刷新占位：当前仅重绘 Stage-1 布局，不触发网络请求。"
        self.refresh_screen()

    def back_to_home(self) -> None:
        self.mode = "home"
        self.status = f"已返回首页占位：{HOME_CHANNEL_LABELS[self.channel_index]}"
        self.refresh_screen()

    def _channel_summary(self) -> str:
        chips: list[str] = []
        for index, label in enumerate(HOME_CHANNEL_LABELS):
            prefix = "●" if index == self.channel_index else "○"
            chips.append(f"{prefix}{index + 1 if index < 9 else 0}.{label}")
        return "  ".join(chips)

    def _shelf_title(self) -> str:
        title_map = {
            "home": "列表 / Shelf",
            "search": "搜索结果 / Search",
            "history": "最近浏览 / History",
            "favorites": "收藏夹 / Favorites",
            "detail": "详情路由 / Detail",
        }
        return title_map.get(self.mode, "列表 / Shelf")

    def _featured_lines(self) -> list[str]:
        return [
            f"当前占位分区：{HOME_CHANNEL_LABELS[self.channel_index]}",
            "未来这里显示推荐卡片、作者、播放量、简介摘要。",
            "当前阶段只验证布局、键位语义与后续挂点。",
        ]

    def _shelf_lines(self) -> list[str]:
        mode_lines = {
            "home": ["首页占位列表", "- 推荐流 / 热门 / 入站必刷 / 分区 / 番剧", "- 保留 n/p 翻页语义"],
            "search": ["搜索占位列表", "- 保留 / 与 s 唤起搜索语义", "- 后续接入 search(keyword, page, page_size)"],
            "history": ["最近浏览占位列表", "- 直接映射 HistoryStore.get_recent_videos()", "- 保留 v 快捷入口"],
            "favorites": ["收藏夹占位列表", "- 直接映射 HistoryStore.get_favorite_videos()", "- 保留 m / f 快捷入口"],
            "detail": ["详情路由占位", "- Enter 从列表切入详情屏", "- 保留 b / Esc 返回语义"],
        }
        return mode_lines.get(self.mode, mode_lines["home"])

    def _detail_lines(self) -> list[str]:
        return [
            "复用候选：build_detail_lines(width)、BilibiliClient.comments()、audio_stream_for_item()。",
            "保留 c 刷新评论、o 浏览器打开、a/x 音频控制、f 收藏语义。",
            "Phase-1 只提供稳定布局和状态提示，不改变现有业务逻辑。",
        ]
