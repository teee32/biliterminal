from __future__ import annotations

import sys
from typing import Any

TEXTUAL_IMPORT_ERROR: ModuleNotFoundError | None = None

try:
    from textual.app import App
    from textual.binding import Binding
    from textual.events import Key
except ModuleNotFoundError as exc:  # pragma: no cover - exercised by smoke tests when deps are absent
    TEXTUAL_IMPORT_ERROR = exc
    App = object  # type: ignore[assignment]
    Binding = None  # type: ignore[assignment]
    Key = Any  # type: ignore[assignment,misc]
else:
    from ..bilibili_cli import BilibiliClient, HistoryStore
    from .screens import HomeScreen

LEGACY_KEYMAP_SUMMARY = [
    ("up/down", "↑/↓ / j/k"),
    ("detail", "Enter"),
    ("back", "Esc / b"),
    ("search", "/ / s"),
    ("channels", "Tab / Shift+Tab / 1-9 / 0"),
    ("history", "v"),
    ("favorites", "m / f"),
    ("audio", "a / x"),
    ("paging", "n / p / PgUp / PgDn"),
    ("browser", "o"),
    ("comments", "c"),
    ("refresh", "r"),
    ("help", "?"),
    ("quit", "q"),
]


if TEXTUAL_IMPORT_ERROR is None:

    class BiliTerminalApp(App[None]):
        """Textual stage-1 app shell for BiliTerminal."""

        CSS_PATH = "styles/bili_dark.tcss"
        TITLE = "BiliTerminal"
        SUB_TITLE = "Textual v0.3.0 stage-1 preview"
        BINDINGS = [
            Binding("up", "move_up", show=False),
            Binding("down", "move_down", show=False),
            Binding("j", "move_up", show=False),
            Binding("k", "move_down", show=False),
            Binding("enter", "show_detail", show=False),
            Binding("escape", "go_back", show=False),
            Binding("b", "go_back", show=False),
            Binding("slash", "focus_search", show=False),
            Binding("s", "focus_search", show=False),
            Binding("tab", "next_channel", show=False),
            Binding("shift+tab", "prev_channel", show=False),
            Binding("l", "rerun_last_search", show=False),
            Binding("d", "default_search", show=False),
            Binding("h", "go_home", show=False),
            Binding("v", "show_history", show=False),
            Binding("m", "show_favorites", show=False),
            Binding("f", "toggle_favorite", show=False),
            Binding("a", "toggle_audio", show=False),
            Binding("x", "stop_audio", show=False),
            Binding("n", "next_page", show=False),
            Binding("p", "prev_page", show=False),
            Binding("pageup", "detail_page_up", show=False),
            Binding("pagedown", "detail_page_down", show=False),
            Binding("o", "open_in_browser", show=False),
            Binding("c", "refresh_comments", show=False),
            Binding("r", "refresh_view", show=False),
            Binding("question_mark", "toggle_help", show=False),
            Binding("q", "quit", show=False),
        ]

        def __init__(
            self,
            *,
            client: BilibiliClient | None = None,
            history_store: HistoryStore | None = None,
        ) -> None:
            super().__init__()
            self.client = client or BilibiliClient()
            self.history_store = history_store or HistoryStore()

        def on_mount(self) -> None:
            self.push_screen(HomeScreen(client=self.client, history_store=self.history_store))

        def on_key(self, event: Key) -> None:
            if event.key in {"0", "1", "2", "3", "4", "5", "6", "7", "8", "9"}:
                self.action_select_channel_shortcut(event.key)
                event.stop()

        def _home(self) -> HomeScreen:
            screen = self.screen
            if not isinstance(screen, HomeScreen):  # pragma: no cover - defensive only
                raise RuntimeError("HomeScreen is not active")
            return screen

        def action_move_up(self) -> None:
            self._home().move_selection(-1)

        def action_move_down(self) -> None:
            self._home().move_selection(1)

        def action_show_detail(self) -> None:
            self._home().show_detail()

        def action_go_back(self) -> None:
            self._home().go_back()

        def action_focus_search(self) -> None:
            self._home().focus_search()

        def action_next_channel(self) -> None:
            self._home().next_channel()

        def action_prev_channel(self) -> None:
            self._home().prev_channel()

        def action_select_channel_shortcut(self, digit: str) -> None:
            self._home().select_channel_shortcut(digit)

        def action_rerun_last_search(self) -> None:
            self._home().rerun_last_search()

        def action_default_search(self) -> None:
            self._home().default_search()

        def action_go_home(self) -> None:
            self._home().go_home()

        def action_show_history(self) -> None:
            self._home().show_history()

        def action_show_favorites(self) -> None:
            self._home().show_favorites()

        def action_toggle_favorite(self) -> None:
            self._home().toggle_favorite()

        def action_toggle_audio(self) -> None:
            self._home().toggle_audio()

        def action_stop_audio(self) -> None:
            self._home().stop_audio()

        def action_next_page(self) -> None:
            self._home().next_page()

        def action_prev_page(self) -> None:
            self._home().prev_page()

        def action_detail_page_up(self) -> None:
            self._home().detail_page_up()

        def action_detail_page_down(self) -> None:
            self._home().detail_page_down()

        def action_open_in_browser(self) -> None:
            self._home().open_in_browser()

        def action_refresh_comments(self) -> None:
            self._home().refresh_comments()

        def action_refresh_view(self) -> None:
            self._home().refresh_view()

        def action_toggle_help(self) -> None:
            self._home().toggle_help()

else:

    class BiliTerminalApp:
        CSS_PATH = "styles/bili_dark.tcss"
        TITLE = "BiliTerminal"
        SUB_TITLE = "Textual v0.3.0 stage-1 preview"
        BINDINGS = tuple(LEGACY_KEYMAP_SUMMARY)

        def run(self) -> None:
            raise RuntimeError(
                "Textual 依赖尚未安装，请执行 `python3 -m pip install -e .` 后再启动新的 UI 骨架。"
            )


def create_app() -> BiliTerminalApp:
    return BiliTerminalApp()


def run_textual_app() -> int:
    if TEXTUAL_IMPORT_ERROR is not None:
        print("Textual 依赖缺失，请先执行 `python3 -m pip install -e .`。", file=sys.stderr)
        return 1
    create_app().run()
    return 0


def main() -> int:
    return run_textual_app()


if __name__ == "__main__":
    raise SystemExit(main())
