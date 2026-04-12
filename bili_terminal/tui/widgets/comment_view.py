from __future__ import annotations

from textual.reactive import reactive
from textual.widgets import Static

from ..utils import CommentSummary


class CommentView(Static):
    """Right-side comment preview panel for the Textual UI."""

    panel_title = reactive("评论预览")
    comments = reactive(tuple())
    empty_message = reactive("按 c 加载评论预览")

    def set_comments(
        self,
        comments: list[CommentSummary],
        *,
        title: str | None = None,
        empty_message: str | None = None,
    ) -> None:
        if title is not None:
            self.panel_title = title
        if empty_message is not None:
            self.empty_message = empty_message
        self.comments = tuple(comments)

    def watch_panel_title(self, _old: str, _new: str) -> None:
        self.update(self._render_text())

    def watch_comments(self, _old: tuple, _new: tuple) -> None:
        self.update(self._render_text())

    def watch_empty_message(self, _old: str, _new: str) -> None:
        self.update(self._render_text())

    def on_mount(self) -> None:
        self.update(self._render_text())

    def _render_text(self) -> str:
        lines = [self.panel_title, ""]
        if not self.comments:
            lines.append(self.empty_message)
            return "\n".join(lines)
        for comment in self.comments:
            lines.extend([f"• {comment.author} · {comment.meta}", comment.message, ""])
        return "\n".join(lines).strip()
