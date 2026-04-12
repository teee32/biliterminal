from __future__ import annotations

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import ListItem, ListView, Static


class ThemePickerScreen(ModalScreen[str | None]):
    """Small modal used by the command palette Theme entry."""

    THEMES: tuple[tuple[str, str, str], ...] = (
        ("dark", "Bilibili Dark", "终端暗黑蓝粉 · 更适合夜间使用"),
        ("light", "Bilibili Light", "B站粉白浅色 · 更接近官网观感"),
    )

    BINDINGS = [
        Binding("up", "cursor_up", show=False),
        Binding("down", "cursor_down", show=False),
        Binding("k", "cursor_up", show=False),
        Binding("j", "cursor_down", show=False),
        Binding("escape", "cancel", "关闭"),
        Binding("b", "cancel", "返回"),
        Binding("q", "cancel", "关闭"),
        Binding("enter", "select_theme", "应用主题"),
    ]

    def __init__(self, *, current_theme: str) -> None:
        super().__init__()
        self.current_theme = current_theme

    def compose(self) -> ComposeResult:
        with Vertical(id="theme-picker-dialog"):
            yield Static("选择主题", id="theme-picker-title")
            yield Static("只提供 BiliTerminal 自己支持的 bilibili 主题", id="theme-picker-subtitle")
            yield ListView(
                *(
                    ListItem(
                        Static(f"{title}\n{description}", classes="theme-picker__item"),
                        id=f"theme-option-{name}",
                    )
                    for name, title, description in self.THEMES
                ),
                id="theme-picker-list",
            )
            yield Static("↑/↓ / j/k 选择 · Enter 应用 · Esc / b 关闭", id="theme-picker-hint")

    def on_mount(self) -> None:
        if hasattr(self.app, "apply_theme_to_screen"):
            self.app.apply_theme_to_screen(self)
        options = [name for name, _, _ in self.THEMES]
        selected_index = options.index(self.current_theme) if self.current_theme in options else 0
        theme_list = self.query_one("#theme-picker-list", ListView)
        theme_list.index = selected_index
        theme_list.focus()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_cursor_up(self) -> None:
        theme_list = self.query_one("#theme-picker-list", ListView)
        current = theme_list.index or 0
        theme_list.index = max(0, current - 1)

    def action_cursor_down(self) -> None:
        theme_list = self.query_one("#theme-picker-list", ListView)
        current = theme_list.index or 0
        theme_list.index = min(len(self.THEMES) - 1, current + 1)

    def action_select_theme(self) -> None:
        theme_list = self.query_one("#theme-picker-list", ListView)
        index = theme_list.index or 0
        theme_name = self.THEMES[max(0, min(index, len(self.THEMES) - 1))][0]
        self.dismiss(theme_name)

    @on(ListView.Selected, "#theme-picker-list")
    def _handle_selected(self, event: ListView.Selected) -> None:
        if event.list_view is self.query_one("#theme-picker-list", ListView):
            self.action_select_theme()
