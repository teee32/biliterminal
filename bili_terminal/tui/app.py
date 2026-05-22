from __future__ import annotations

import sys
from typing import Any

from .keymap import (
    APP_BINDING_SPECS,
    APP_CHANNEL_SHORTCUT_KEYS,
    KEYMAP_GROUPS,
    KEYMAP_SUMMARY,
    THEME_MENU_SOURCE_TEXT,
    THEME_TOGGLE_SOURCE_TEXT,
)

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
    from ..core import BilibiliClient, HistoryStore
    from .screens import FavoritesScreen, HistoryScreen, HomeScreen, SearchScreen, ThemePickerScreen, WatchLaterScreen
    from .utils import (
        TUI_THEME_NAMES,
        TextualAdapter,
        format_theme_status_message,
        load_tui_config,
        normalize_tui_theme,
        save_tui_config,
    )

APP_CSS_PATH = "styles/bili_dark.tcss"
APP_TITLE = "BiliTerminal"
APP_SUB_TITLE = "Textual v0.3.1"
APP_ENABLE_COMMAND_PALETTE = True


def build_app_bindings() -> tuple[Any, ...]:
    if Binding is None:
        return ()
    return tuple(Binding(key, action, show=False) for key, action in APP_BINDING_SPECS)


if TEXTUAL_IMPORT_ERROR is None:

    class BiliTerminalApp(App[None]):
        """Textual app shell for BiliTerminal v0.3.1."""

        CSS_PATH = APP_CSS_PATH
        TITLE = APP_TITLE
        SUB_TITLE = APP_SUB_TITLE
        ENABLE_COMMAND_PALETTE = APP_ENABLE_COMMAND_PALETTE
        BINDINGS = build_app_bindings()

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
            if event.key in APP_CHANNEL_SHORTCUT_KEYS:
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
            active_theme = self.tui_config.theme
            for theme in TUI_THEME_NAMES:
                class_name = f"theme-{theme}"
                enabled = active_theme == theme
                self.set_class(enabled, class_name)
                screen.set_class(enabled, class_name)
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

        def _set_current_screen_status(self, message: str) -> None:
            status_setter = getattr(self.screen, "set_status", None)
            if callable(status_setter):
                status_setter(message)

        def set_theme(self, theme: str, *, source: str = THEME_TOGGLE_SOURCE_TEXT) -> None:
            normalized = normalize_tui_theme(theme)
            if normalized == self.tui_config.theme:
                self._set_current_screen_status(format_theme_status_message(normalized, source, unchanged=True))
                return
            self.tui_config = save_tui_config(normalized, self.tui_config.path)
            self.sync_theme()
            self._set_current_screen_status(format_theme_status_message(normalized, source))

        def _handle_theme_selection(self, theme: str | None) -> None:
            if theme:
                self.set_theme(theme, source=THEME_MENU_SOURCE_TEXT)

        def action_change_theme(self) -> None:
            self.push_screen(
                ThemePickerScreen(current_theme=self.tui_config.theme),
                callback=self._handle_theme_selection,
            )

        def action_toggle_theme(self) -> None:
            current_index = TUI_THEME_NAMES.index(self.tui_config.theme)
            next_theme = TUI_THEME_NAMES[(current_index + 1) % len(TUI_THEME_NAMES)]
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

        def open_watch_later(self) -> None:
            self.push_screen(WatchLaterScreen(adapter=self.adapter, initial_audio=self.audio_status))

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

        def action_show_watch_later(self) -> None:
            self._dispatch("show_watch_later")

        def action_toggle_favorite(self) -> None:
            self._dispatch("toggle_favorite")

        def action_toggle_watch_later(self) -> None:
            self._dispatch("toggle_watch_later")

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
        CSS_PATH = APP_CSS_PATH
        TITLE = APP_TITLE
        SUB_TITLE = APP_SUB_TITLE
        ENABLE_COMMAND_PALETTE = APP_ENABLE_COMMAND_PALETTE
        BINDINGS = tuple(KEYMAP_SUMMARY)

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
