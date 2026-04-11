from __future__ import annotations

import sys
from typing import Any

TEXTUAL_IMPORT_ERROR: ModuleNotFoundError | None = None

try:
    from textual.app import App
    from textual.binding import Binding
    from textual.events import Key
except ModuleNotFoundError as exc:  # pragma: no cover - exercised indirectly in smoke tests
    TEXTUAL_IMPORT_ERROR = exc
    App = object  # type: ignore[assignment]
    Binding = None  # type: ignore[assignment]
    Key = Any  # type: ignore[assignment,misc]
else:
    from .screens import HomeScreen


LEGACY_KEYMAP_SUMMARY = [
    ("Tab", "next-channel"),
    ("Shift+Tab", "previous-channel"),
    ("1-0", "direct-channel"),
    ("/", "search"),
    ("Enter", "detail"),
    ("b", "back-home"),
    ("v", "history"),
    ("m", "favorites"),
    ("a", "audio-toggle"),
    ("x", "audio-stop"),
    ("f", "favorite-toggle"),
    ("c", "comments-refresh"),
    ("r", "refresh"),
    ("l", "rerun-search"),
    ("d", "default-search"),
    ("q", "quit"),
]


if TEXTUAL_IMPORT_ERROR is None:

    class BiliTerminalTextualApp(App[None]):
        """Stage-1 Textual skeleton that preserves the legacy keymap intent."""

        CSS_PATH = "styles.tcss"
        TITLE = "BiliTerminal"
        SUB_TITLE = "Textual phase-1 architecture shell"
        BINDINGS = [
            Binding("tab", "next_channel", "Next channel"),
            Binding("shift+tab", "previous_channel", "Previous channel"),
            Binding("slash", "search", "Search"),
            Binding("s", "search", "Search"),
            Binding("enter", "show_detail", "Detail"),
            Binding("b", "back_home", "Back"),
            Binding("h", "back_home", "Home"),
            Binding("v", "show_history", "History"),
            Binding("m", "show_favorites", "Favorites"),
            Binding("a", "toggle_audio", "Audio"),
            Binding("x", "stop_audio", "Stop audio"),
            Binding("f", "toggle_favorite", "Favorite"),
            Binding("c", "show_comments", "Comments"),
            Binding("r", "refresh_placeholder", "Refresh"),
            Binding("l", "rerun_last_search", "Rerun search"),
            Binding("d", "default_search", "Default search"),
            Binding("q", "quit", "Quit"),
        ]

        def on_mount(self) -> None:
            self.push_screen(HomeScreen())

        def _home_screen(self) -> HomeScreen:
            screen = self.screen
            if not isinstance(screen, HomeScreen):  # pragma: no cover - defensive only
                raise RuntimeError("HomeScreen is not active")
            return screen

        def action_next_channel(self) -> None:
            self._home_screen().cycle_channel(1)

        def action_previous_channel(self) -> None:
            self._home_screen().cycle_channel(-1)

        def action_search(self) -> None:
            self._home_screen().show_search_placeholder()

        def action_show_detail(self) -> None:
            self._home_screen().show_detail_placeholder()

        def action_back_home(self) -> None:
            self._home_screen().back_to_home()

        def action_show_history(self) -> None:
            self._home_screen().show_history_placeholder()

        def action_show_favorites(self) -> None:
            self._home_screen().show_favorites_placeholder()

        def action_toggle_audio(self) -> None:
            self._home_screen().toggle_audio_placeholder()

        def action_stop_audio(self) -> None:
            self._home_screen().stop_audio_placeholder()

        def action_toggle_favorite(self) -> None:
            self._home_screen().toggle_favorite_placeholder()

        def action_show_comments(self) -> None:
            self._home_screen().show_comments_placeholder()

        def action_refresh_placeholder(self) -> None:
            self._home_screen().refresh_placeholder()

        def action_rerun_last_search(self) -> None:
            self._home_screen().rerun_last_search_placeholder()

        def action_default_search(self) -> None:
            self._home_screen().show_search_placeholder()

        def on_key(self, event: Key) -> None:
            if event.key in {"0", "1", "2", "3", "4", "5", "6", "7", "8", "9"}:
                self._home_screen().direct_channel(event.key)
                event.stop()

else:

    class BiliTerminalTextualApp:
        """Fallback object that keeps imports friendly when Textual is not installed."""

        CSS_PATH = "styles.tcss"
        TITLE = "BiliTerminal"
        SUB_TITLE = "Textual phase-1 architecture shell"
        BINDINGS: tuple[tuple[str, str], ...] = tuple(LEGACY_KEYMAP_SUMMARY)

        def run(self) -> None:
            raise RuntimeError(
                "Textual is not installed. Run `python3 -m pip install -e .[textual]` before starting the new UI shell."
            )


def create_app() -> BiliTerminalTextualApp:
    return BiliTerminalTextualApp()


def main() -> int:
    if TEXTUAL_IMPORT_ERROR is not None:
        print(
            "Textual dependency missing. Install it with `python3 -m pip install -e .[textual]` to run the phase-1 UI shell.",
            file=sys.stderr,
        )
        return 1
    create_app().run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
