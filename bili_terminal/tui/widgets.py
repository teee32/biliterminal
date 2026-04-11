from __future__ import annotations

from textual.widgets import Static


class PlaceholderPanel(Static):
    """Simple reusable stage-1 panel for app scaffolding."""

    def __init__(self, title: str, body: list[str] | None = None, *, panel_id: str | None = None) -> None:
        self.panel_title = title
        self.panel_body = list(body or [])
        super().__init__(self._render_text(), id=panel_id, classes="placeholder-panel")

    def set_panel(self, *, title: str | None = None, body: list[str] | None = None) -> None:
        if title is not None:
            self.panel_title = title
        if body is not None:
            self.panel_body = list(body)
        self.update(self._render_text())

    def _render_text(self) -> str:
        lines = [self.panel_title, "", *(self.panel_body or ["等待后续核心能力接入..."])]
        return "\n".join(lines)


class KeymapLegend(Static):
    """Compact legend that preserves the legacy keymap intent."""

    def __init__(self, entries: list[tuple[str, str]], *, legend_id: str | None = None) -> None:
        self.entries = list(entries)
        super().__init__(self._render_text(), id=legend_id, classes="keymap-legend", markup=False)

    def _render_text(self) -> str:
        return " · ".join(f"[{key}] {label}" for key, label in self.entries)
