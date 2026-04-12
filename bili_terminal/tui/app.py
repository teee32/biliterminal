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
    from .screens import FavoritesScreen, HistoryScreen, HomeScreen, SearchScreen, ThemePickerScreen
    from .utils import TextualAdapter, load_tui_config, save_tui_config

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
        """Textual app shell for BiliTerminal v0.3.0."""

        CSS_PATH = "styles/bili_dark.tcss"
        TITLE = "BiliTerminal"
        SUB_TITLE = "Textual v0.3.0"
        ENABLE_COMMAND_PALETTE = True
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
            Binding("ctrl+t", "toggle_theme", show=False),
            Binding("f2", "toggle_theme", show=False),
            Binding("question_mark", "toggle_help", show=False),
            Binding("q", "quit", show=False),
        ]

        def __init__(
            self,
            *,
            client: BilibiliClient | None = None,
            history_store: HistoryStore | None = None,
            adapter: TextualAdapter | None = None,
        ) -> None:
            super().__init__()
            self.client = client or BilibiliClient()
            self.history_store = history_store or HistoryStore()
            self.adapter = adapter or TextualAdapter(client=self.client, history_store=self.history_store)
            self.audio_status = self.adapter.current_audio_status()
            self.tui_config = load_tui_config()
            self._home_screen = HomeScreen(adapter=self.adapter, initial_audio=self.audio_status)

        def on_mount(self) -> None:
            self.install_screen(self._home_screen, "home")
            self.push_screen("home")
            self.sync_theme()
            self.set_interval(1.0, self._poll_config)

        def on_key(self, event: Key) -> None:
            if event.key in {"0", "1", "2", "3", "4", "5", "6", "7", "8", "9"}:
                self.action_select_channel_shortcut(event.key)
                event.stop()

        def update_audio_status(self, status) -> None:
            self.audio_status = status

        def _theme_targets(self):
            seen: set[int] = set()
            for screen in [self._home_screen, *self.screen_stack]:
                identifier = id(screen)
                if identifier in seen:
                    continue
                seen.add(identifier)
                yield screen

        def apply_theme_to_screen(self, screen) -> None:
            is_light = self.tui_config.theme == "light"
            self.set_class(is_light, "theme-light")
            self.set_class(not is_light, "theme-dark")
            screen.set_class(is_light, "theme-light")
            screen.set_class(not is_light, "theme-dark")
            screen.refresh(repaint=True, layout=True)

        def sync_theme(self) -> None:
            for screen in self._theme_targets():
                self.apply_theme_to_screen(screen)
            self.refresh(repaint=True, layout=True)

        def _poll_config(self) -> None:
            latest = load_tui_config(self.tui_config.path)
            if latest.theme == self.tui_config.theme and latest.mtime == self.tui_config.mtime:
                return
            self.tui_config = latest
            self.sync_theme()

        def set_theme(self, theme: str, *, source: str = "Ctrl+T / F2") -> None:
            normalized = "light" if str(theme).lower() == "light" else "dark"
            if normalized == self.tui_config.theme:
                current_screen = self.screen
                status_setter = getattr(current_screen, "set_status", None)
                if callable(status_setter):
                    status_setter(f"当前已是{'浅色' if normalized == 'light' else '深色'}主题（{source}）")
                return
            self.tui_config = save_tui_config(normalized, self.tui_config.path)
            self.sync_theme()
            current_screen = self.screen
            status_setter = getattr(current_screen, "set_status", None)
            if callable(status_setter):
                status_setter(f"主题已切换为 {'浅色' if normalized == 'light' else '深色'}（{source}）")

        def _handle_theme_selection(self, theme: str | None) -> None:
            if theme:
                self.set_theme(theme, source="主题菜单")

        def action_change_theme(self) -> None:
            self.push_screen(
                ThemePickerScreen(current_theme=self.tui_config.theme),
                callback=self._handle_theme_selection,
            )

        def action_toggle_theme(self) -> None:
            next_theme = "light" if self.tui_config.theme == "dark" else "dark"
            self.set_theme(next_theme)

        def get_system_commands(self, screen):
            help_handler = getattr(screen, "toggle_help", None)
            yield ("Theme", "切换 BiliTerminal 主题", self.action_change_theme, True)
            if callable(help_handler):
                yield ("Keys", "显示 / 关闭当前页面快捷键帮助", help_handler, True)
            for name, help_text, callback, discover in super().get_system_commands(screen):
                if name in {"Theme", "Keys"}:
                    continue
                yield (name, help_text, callback, discover)

        def return_home(self) -> None:
            while len(self.screen_stack) > 1:
                self.pop_screen()
            self.call_after_refresh(self._home_screen.focus_video_list)

        def activate_home_channel(self, index: int) -> None:
            self.return_home()
            self.call_after_refresh(lambda: self._home_screen.set_channel(index))

        def open_search(self, *, keyword: str = "") -> None:
            self.push_screen(SearchScreen(adapter=self.adapter, initial_audio=self.audio_status, keyword=keyword))

        def open_history(self) -> None:
            self.push_screen(HistoryScreen(adapter=self.adapter, initial_audio=self.audio_status))

        def open_favorites(self) -> None:
            self.push_screen(FavoritesScreen(adapter=self.adapter, initial_audio=self.audio_status))

        def _dispatch(self, method_name: str, *args: Any) -> None:
            handler = getattr(self.screen, method_name, None)
            if callable(handler):
                handler(*args)

        def action_move_up(self) -> None:
            self._dispatch("move_selection", -1)

        def action_move_down(self) -> None:
            self._dispatch("move_selection", 1)

        def action_show_detail(self) -> None:
            self._dispatch("show_detail")

        def action_go_back(self) -> None:
            self._dispatch("go_back")

        def action_focus_search(self) -> None:
            self._dispatch("focus_search")

        def action_next_channel(self) -> None:
            self._dispatch("next_channel")

        def action_prev_channel(self) -> None:
            self._dispatch("prev_channel")

        def action_select_channel_shortcut(self, digit: str) -> None:
            self._dispatch("select_channel_shortcut", digit)

        def action_rerun_last_search(self) -> None:
            self._dispatch("rerun_last_search")

        def action_default_search(self) -> None:
            self._dispatch("default_search")

        def action_go_home(self) -> None:
            self._dispatch("go_home")

        def action_show_history(self) -> None:
            self._dispatch("show_history")

        def action_show_favorites(self) -> None:
            self._dispatch("show_favorites")

        def action_toggle_favorite(self) -> None:
            self._dispatch("toggle_favorite")

        def action_toggle_audio(self) -> None:
            self._dispatch("toggle_audio")

        def action_stop_audio(self) -> None:
            self._dispatch("stop_audio")

        def action_next_page(self) -> None:
            self._dispatch("next_page")

        def action_prev_page(self) -> None:
            self._dispatch("prev_page")

        def action_detail_page_up(self) -> None:
            self._dispatch("detail_page_up")

        def action_detail_page_down(self) -> None:
            self._dispatch("detail_page_down")

        def action_open_in_browser(self) -> None:
            self._dispatch("open_in_browser")

        def action_refresh_comments(self) -> None:
            self._dispatch("refresh_comments")

        def action_refresh_view(self) -> None:
            self._dispatch("refresh_view")

        def action_toggle_help(self) -> None:
            self._dispatch("toggle_help")

else:

    class BiliTerminalApp:
        CSS_PATH = "styles/bili_dark.tcss"
        TITLE = "BiliTerminal"
        SUB_TITLE = "Textual v0.3.0"
        BINDINGS = tuple(LEGACY_KEYMAP_SUMMARY)

        def run(self) -> None:
            raise RuntimeError(
                "Textual 依赖尚未安装，请执行 `python3 -m pip install -e .` 后再启动新的 UI。"
            )



def create_app(
    *,
    client=None,
    history_store=None,
    adapter=None,
) -> BiliTerminalApp:
    if TEXTUAL_IMPORT_ERROR is not None:
        return BiliTerminalApp()
    return BiliTerminalApp(client=client, history_store=history_store, adapter=adapter)



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
