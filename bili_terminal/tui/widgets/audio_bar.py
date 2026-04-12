from __future__ import annotations

from textual.reactive import reactive
from textual.widgets import Static

from ..utils import AudioStatus, DEFAULT_AUDIO_STATUS


class AudioBar(Static):
    """Global bottom audio control bar used by the Textual shell."""

    now_playing = reactive("未播放")
    play_state = reactive("stopped")
    status_message = reactive(DEFAULT_AUDIO_STATUS)

    def on_mount(self) -> None:
        self.update(self._line())

    def watch_now_playing(self, _old: str, _new: str) -> None:
        self.update(self._line())

    def watch_play_state(self, _old: str, _new: str) -> None:
        self.update(self._line())

    def watch_status_message(self, _old: str, _new: str) -> None:
        self.update(self._line())

    def set_track(self, title: str, *, state: str = "playing") -> None:
        self.now_playing = title
        self.play_state = state

    def set_status(self, message: str) -> None:
        self.status_message = message

    def set_audio_status(self, status: AudioStatus) -> None:
        self.now_playing = status.now_playing
        self.play_state = status.state
        self.status_message = status.status_message

    def stop(self) -> None:
        self.play_state = "stopped"
        self.now_playing = "未播放"

    def _line(self) -> str:
        icon = {
            "playing": "▶",
            "paused": "Ⅱ",
            "stopped": "■",
        }.get(self.play_state, "■")
        return f"{icon} {self.now_playing}    {self.status_message}"
