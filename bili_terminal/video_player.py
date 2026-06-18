"""ASCII 字符画视频播放引擎。

通过 ffmpeg 管道解码视频 → raw RGB 帧 → 灰度转换 + Floyd-Steinberg 抖动 →
纯 ASCII 字符画，全屏终端渲染，约 10fps。
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from typing import TYPE_CHECKING

from .paths import default_state_dir

if TYPE_CHECKING:
    from .client import BilibiliClient
    from .models import VideoStream, VideoItem

# 运行时需要真实类型用于 except 匹配（不能放进 TYPE_CHECKING）
from .models import BilibiliAPIError

# ── 视频播放日志 ──────────────────────────────────────────────


def _video_log_path() -> str:
    return os.path.join(default_state_dir(), "video-playback.log")


def _write_video_log(message: str) -> None:
    path = _video_log_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {message}\n")
    except OSError:
        pass

# ── 终端格宽比 ──────────────────────────────────────────────
# 终端字符格通常约为 宽:高 ≈ 1:2（取决于字体，但 2.0 是合理的默认值）
# 视频通常为 16:9。在终端中显示需要校正：
#   终端 cols:rows = 16/1 : 9/2 = 16 : 4.5 ≈ 3.56:1
CELL_ASPECT_RATIO = 2.0

# ── ASCII 字符渐变表 ─────────────────────────────────────────
# 从暗（空格 = 黑像素，在暗色终端上不可见）到亮（@ = 白像素，墨量最大）。
# 适用于暗色终端背景。共 10 级。
# 若终端为浅色背景，可反转为 "@%#*+=-:. "。
ASCII_CHAR_RAMP = " .:-=+*#%@"


def calc_video_dimensions(
    available_cols: int,
    available_rows: int,
    video_aspect: float = 16.0 / 9.0,
) -> tuple[int, int]:
    """给定可用终端区域，计算视频渲染 of cols×rows。

    返回的 (cols, rows) 在终端渲染后会保持原视频宽高比。
    ffmpeg 缩放尺寸为 (cols, rows)，每个终端字符对应一个像素。
    """
    if available_cols <= 0 or available_rows <= 0:
        return 20, 5
    # 限制最大渲染分辨率以防 CPU 耗尽（由于 Floyd-Steinberg 和灰度转换由纯 Python 实现）
    available_cols = min(available_cols, 120)
    available_rows = min(available_rows, 40)
    # 终端格换算后的目标宽高比
    target_ratio = video_aspect * CELL_ASPECT_RATIO
    if available_cols / max(available_rows, 1) > target_ratio:
        # 宽度充足，限宽
        cols = min(available_cols, int(available_rows * target_ratio))
        rows = available_rows
    else:
        # 高度充足，限高
        cols = available_cols
        rows = min(available_rows, int(available_cols / target_ratio))
    return max(cols, 20), max(rows, 5)


def _video_state_path() -> str:
    return os.path.join(default_state_dir(), "video-playback.json")


def _save_video_state(state: "VideoPlaybackState") -> None:
    from .models import VideoPlaybackState

    path = _video_state_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(
            {
                "pid": state.pid,
                "title": state.title,
                "video_key": state.video_key,
                "playing": state.playing,
                "target_cols": state.target_cols,
                "target_rows": state.target_rows,
                "target_fps": state.target_fps,
            },
            handle,
            ensure_ascii=False,
            indent=2,
        )


def _clear_video_state() -> None:
    try:
        os.unlink(_video_state_path())
    except FileNotFoundError:
        pass


def _load_video_state() -> "VideoPlaybackState | None":
    from .models import VideoPlaybackState

    path = _video_state_path()
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    if not isinstance(payload, dict):
        _clear_video_state()
        return None
    try:
        return VideoPlaybackState(
            pid=payload.get("pid"),
            title=str(payload.get("title") or ""),
            video_key=payload.get("video_key"),
            playing=bool(payload.get("playing", True)),
            target_cols=int(payload.get("target_cols", 80)),
            target_rows=int(payload.get("target_rows", 24)),
            target_fps=int(payload.get("target_fps", 10)),
        )
    except (TypeError, ValueError):
        _clear_video_state()
        return None


def _pid_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


# ── ffmpeg 命令 ─────────────────────────────────────────────


def _build_ffmpeg_command(
    stream: "VideoStream",
    cols: int,
    rows: int,
    fps: int = 10,
) -> list[str]:
    """构建 ffmpeg 子进程命令。

    输出 raw RGB24 到 stdout pipe，尺寸为 cols × rows。
    每个终端字符对应一个像素。
    """
    scale_w = cols
    scale_h = rows
    scale_filter = f"scale={scale_w}:{scale_h}:flags=neighbor"

    # -re 让 ffmpeg 以原生帧率实时读取输入流（网络流也适用），
    # 避免一口气解码完全部帧导致视频瞬间播完而音频仍在正常速度播放，
    # 从源头保证音画大致同步。
    command = [
        "ffmpeg",
        "-re",
    ]
    if getattr(stream, "cookie_header", ""):
        command.extend(["-i", "pipe:0"])
    else:
        headers = f"Referer: {stream.referer}\r\nUser-Agent: {stream.user_agent}\r\n"
        command.extend(["-headers", headers, "-i", stream.url])
    command.extend([
        "-vf",
        f"{scale_filter},fps={fps}",
        "-pix_fmt",
        "rgb24",
        "-f",
        "rawvideo",
        "-an",
        "-nostdin",
        "-loglevel",
        "error",
        "pipe:1",
    ])
    return command


def _redact_ffmpeg_command(command: list[str]) -> list[str]:
    redacted = list(command)
    try:
        header_index = redacted.index("-headers") + 1
    except ValueError:
        return redacted
    if header_index >= len(redacted):
        return redacted
    header_lines = []
    for line in redacted[header_index].splitlines():
        if line.lower().startswith("cookie:"):
            header_lines.append("Cookie: <redacted>")
        else:
            header_lines.append(line)
    redacted[header_index] = "\\r\\n".join(header_lines)
    return redacted


# ── RGB → ASCII 字符画渲染 ──────────────────────────────────


def _apply_floyd_steinberg(gray: bytearray, cols: int, rows: int) -> None:
    """Floyd-Steinberg 误差扩散抖动，原地修改灰度数组。

    将 0..255 灰度值量化到 ASCII_CHAR_RAMP 的级数，
    把量化误差扩散到右/下/左下/右下邻像素，消除色阶断层。
    """
    levels = len(ASCII_CHAR_RAMP)
    if levels < 2:
        return

    for y in range(rows):
        for x in range(cols):
            idx = y * cols + x
            old = gray[idx]
            # 量化到最近级
            level = (old * (levels - 1) + 127) // 255
            new = level * 255 // (levels - 1)
            gray[idx] = new
            error = old - new
            # 分发误差到邻像素
            if x + 1 < cols:
                v = gray[idx + 1] + error * 7 // 16
                gray[idx + 1] = max(0, min(255, v))
            if y + 1 < rows:
                if x > 0:
                    v = gray[idx + cols - 1] + error * 3 // 16
                    gray[idx + cols - 1] = max(0, min(255, v))
                v = gray[idx + cols] + error * 5 // 16
                gray[idx + cols] = max(0, min(255, v))
                if x + 1 < cols:
                    v = gray[idx + cols + 1] + error * 1 // 16
                    gray[idx + cols + 1] = max(0, min(255, v))


def render_frame(rgb_data: bytes, cols: int, rows: int) -> str:
    """将 raw RGB24 帧数据转为纯 ASCII 字符画。

    每个终端字符 = 一个像素。
    先转灰度 (ITU-R BT.601)，再经 Floyd-Steinberg 抖动，
    最后查表映射为 ASCII 字符。

    rgb_data 布局: rows 行, 每行 cols 像素, 每像素 3 字节 (R,G,B)
    返回纯文本字符串，无 ANSI 转义序列。
    """
    if cols <= 0 or rows <= 0:
        return ""
    total = rows * cols
    expected = total * 3
    if len(rgb_data) < expected:
        raise ValueError(f"RGB 帧数据过短: {len(rgb_data)} < {expected}")

    # 1. RGB → 灰度 (BT.601: Y = 0.299R + 0.587G + 0.114B)
    gray = bytearray(total)
    for i in range(total):
        r = rgb_data[i * 3]
        g = rgb_data[i * 3 + 1]
        b = rgb_data[i * 3 + 2]
        gray[i] = (77 * r + 150 * g + 29 * b) >> 8  # /256, 位运算更快

    # 2. Floyd-Steinberg 误差扩散
    _apply_floyd_steinberg(gray, cols, rows)

    # 3. 灰度 → ASCII 字符
    ramp = ASCII_CHAR_RAMP
    levels = len(ramp)
    lines: list[str] = []
    for row in range(rows):
        base = row * cols
        chars: list[str] = []
        for col in range(cols):
            level = gray[base + col] * levels >> 8  # /256
            chars.append(ramp[level])
        lines.append("".join(chars))

    return "\n".join(lines)


# ── 帧读取器（线程）─────────────────────────────────────────


class FrameReader:
    """在独立线程中从 ffmpeg stdout 读取原始 RGB 帧。"""

    def __init__(self, process: subprocess.Popen, cols: int, rows: int):
        self._process = process
        self._frame_byte_size = cols * rows * 3  # cols × rows × 3 bytes (RGB)
        self._lock = threading.Lock()
        self._current_frame: bytes | None = None
        self._running = False
        self._thread: threading.Thread | None = None

    @property
    def frame_byte_size(self) -> int:
        return self._frame_byte_size

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._read_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=1.0)

    def get_latest_frame(self) -> bytes | None:
        with self._lock:
            frame = self._current_frame
            self._current_frame = None
            return frame

    def get_latest_frame_peek(self) -> bytes | None:
        """获取最新帧但不消费（用于重复渲染同一帧）。"""
        with self._lock:
            return self._current_frame

    def _read_loop(self) -> None:
        buf = bytearray()
        target = self._frame_byte_size
        try:
            while self._running:
                if self._process.stdout is None:
                    break
                chunk = self._process.stdout.read(max(target - len(buf), 4096))
                if not chunk:
                    break
                buf.extend(chunk)
                while len(buf) >= target:
                    frame = bytes(buf[:target])
                    del buf[:target]
                    with self._lock:
                        self._current_frame = frame
        except (OSError, ValueError):
            pass


class StreamFeeder:
    """在独立线程中把认证 HTTP 流写入 ffmpeg stdin，避免 Cookie 出现在进程参数里。"""

    def __init__(self, process: subprocess.Popen, stream: "VideoStream"):
        self._process = process
        self._stream = stream
        self._running = False
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._feed_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        stdin = self._process.stdin
        if stdin is not None:
            try:
                stdin.close()
            except OSError:
                pass
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=1.0)

    def _feed_loop(self) -> None:
        stdin = self._process.stdin
        if stdin is None:
            return
        headers = {
            "Referer": self._stream.referer,
            "User-Agent": self._stream.user_agent,
            "Accept": "*/*",
            "Cookie": self._stream.cookie_header,
        }
        request = urllib.request.Request(self._stream.url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                while self._running:
                    chunk = response.read(256 * 1024)
                    if not chunk:
                        break
                    stdin.write(chunk)
                    stdin.flush()
        except (BrokenPipeError, OSError, urllib.error.URLError):
            pass
        finally:
            try:
                stdin.close()
            except OSError:
                pass


# ── 视频播放器 ──────────────────────────────────────────────


class VideoPlayer:
    """管理 ffmpeg 子进程和帧渲染的完整生命周期。"""

    def __init__(
        self,
        stream: "VideoStream",
        cols: int,
        rows: int,
        fps: int = 10,
        video_key: str | None = None,
    ):
        self._stream = stream
        self._cols = cols
        self._rows = rows
        self._fps = fps
        self._video_key = video_key
        self._process: subprocess.Popen | None = None
        self._reader: FrameReader | None = None
        self._feeder: StreamFeeder | None = None
        self._paused = False
        self._last_render: str | None = None
        self._stderr_handle: object = None

    @property
    def cols(self) -> int:
        return self._cols

    @property
    def rows(self) -> int:
        return self._rows

    @property
    def fps(self) -> int:
        return self._fps

    @property
    def paused(self) -> bool:
        return self._paused

    def start(self) -> None:
        """启动 ffmpeg 子进程和帧读取线程。"""
        from .models import VideoPlaybackState

        self.stop(silent=True)

        command = _build_ffmpeg_command(self._stream, self._cols, self._rows, self._fps)
        _write_video_log(f"启动 ffmpeg: {' '.join(_redact_ffmpeg_command(command))}")
        stderr_log_path = _video_log_path()
        self._stderr_handle = open(stderr_log_path, "ab")
        try:
            self._process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=self._stderr_handle,
                stdin=subprocess.PIPE if getattr(self._stream, "cookie_header", "") else subprocess.DEVNULL,
            )
        except Exception:
            try:
                self._stderr_handle.close()
            except OSError:
                pass
            self._stderr_handle = None
            raise
        self._reader = FrameReader(self._process, self._cols, self._rows)
        self._reader.start()
        if getattr(self._stream, "cookie_header", ""):
            self._feeder = StreamFeeder(self._process, self._stream)
            self._feeder.start()
        self._paused = False
        self._last_render = None

        _save_video_state(
            VideoPlaybackState(
                pid=self._process.pid,
                title=self._stream.url.split("/")[-1][:40],
                video_key=self._video_key,
                playing=True,
                target_cols=self._cols,
                target_rows=self._rows,
                target_fps=self._fps,
            )
        )

    def stop(self, *, silent: bool = False) -> None:
        """停止 ffmpeg 和帧读取器。"""
        reader = self._reader
        feeder = self._feeder
        process = self._process

        if reader is not None:
            reader._running = False
        self._reader = None
        self._feeder = None

        if feeder is not None:
            feeder.stop()

        if process is not None:
            try:
                if process.poll() is None:
                    if self._paused:
                        try:
                            process.send_signal(signal.SIGCONT)
                        except ProcessLookupError:
                            pass
                    process.send_signal(signal.SIGTERM)
                    try:
                        process.wait(timeout=2.0)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        try:
                            process.wait(timeout=1.0)
                        except subprocess.TimeoutExpired:
                            _write_video_log("ffmpeg SIGKILL 后仍未退出")
                exit_code = process.poll()
                if exit_code is not None and exit_code != 0:
                    _write_video_log(f"ffmpeg 异常退出 (exit={exit_code}), stderr 见上方日志")
            except (ProcessLookupError, OSError):
                pass
        self._process = None

        if reader is not None:
            if reader._thread is not None and reader._thread.is_alive():
                reader._thread.join(timeout=1.0)

        self._paused = False
        self._last_render = None
        _clear_video_state()

        # 关闭 stderr 文件句柄
        if self._stderr_handle is not None:
            try:
                self._stderr_handle.close()
            except OSError:
                pass
        self._stderr_handle = None

    def pause(self) -> None:
        """暂停视频（SIGSTOP ffmpeg 进程）。"""
        if self._process is None or self._paused:
            return
        try:
            if self._process.poll() is None:
                self._process.send_signal(signal.SIGSTOP)
                self._paused = True
                _save_video_state(
                    _load_video_state() or _make_minimal_state(self),
                )
                # 覆盖 paused 标记
                state = _load_video_state()
                if state:
                    state.playing = False
                    _save_video_state(state)
        except (ProcessLookupError, OSError):
            pass

    def resume(self) -> None:
        """继续视频（SIGCONT ffmpeg 进程）。"""
        if self._process is None or not self._paused:
            return
        try:
            if self._process.poll() is None:
                self._process.send_signal(signal.SIGCONT)
                self._paused = False
                state = _load_video_state()
                if state:
                    state.playing = True
                    _save_video_state(state)
        except (ProcessLookupError, OSError):
            pass

    def toggle_pause(self) -> bool:
        """切换暂停状态，返回是否处于播放中。"""
        if self._paused:
            self.resume()
        else:
            self.pause()
        return not self._paused

    def get_frame(self) -> str | None:
        """非阻塞获取最新渲染帧的 ANSI 字符串。

        如果有新帧则渲染并返回，否则返回 None。
        暂停时返回上一帧的缓存。
        """
        if self._reader is None:
            return None

        if self._paused:
            return self._last_render

        raw = self._reader.get_latest_frame()
        if raw is not None and len(raw) >= self._reader.frame_byte_size:
            frame = render_frame(raw, self._cols, self._rows)
            self._last_render = frame
            return frame
        return None

    def get_last_frame(self) -> str | None:
        """获取上一帧缓存（不消费新帧）。"""
        if self._last_render is not None:
            return self._last_render
        if self._reader is None:
            return None
        raw = self._reader.get_latest_frame_peek()
        if raw is not None and len(raw) >= self._reader.frame_byte_size:
            frame = render_frame(raw, self._cols, self._rows)
            self._last_render = frame
            return frame
        return None

    def is_alive(self) -> bool:
        """检查 ffmpeg 进程是否仍在运行。"""
        if self._process is None:
            return False
        alive = self._process.poll() is None
        if not alive and self._last_render is not None:
            exit_code = self._process.returncode
            if exit_code != 0 and exit_code != -15:  # -15 = SIGTERM（主动停止，正常）
                _write_video_log(
                    f"ffmpeg 意外退出 (exit={exit_code}), "
                    f"stderr 详情见 {_video_log_path()}"
                )
        return alive


def _make_minimal_state(player: VideoPlayer) -> "VideoPlaybackState":
    from .models import VideoPlaybackState

    return VideoPlaybackState(
        pid=player._process.pid if player._process else None,
        title="",
        video_key=player._video_key,
        playing=not player._paused,
        target_cols=player._cols,
        target_rows=player._rows,
        target_fps=player._fps,
    )


# ── 便捷入口 ────────────────────────────────────────────────


def video_stream_for_item(client: "BilibiliClient", item: "VideoItem") -> "VideoStream":
    """从 VideoItem 获取视频流。"""
    return client.video_stream_for_item(item)


def has_ffmpeg() -> bool:
    """检查系统是否有 ffmpeg。"""
    return shutil.which("ffmpeg") is not None


def play_video_for_item(
    client: "BilibiliClient",
    item: "VideoItem",
    cols: int = 80,
    rows: int = 24,
    fps: int = 10,
) -> VideoPlayer | None:
    """为指定视频创建并启动 VideoPlayer。

    返回 VideoPlayer 实例，或 None（无 ffmpeg / 无法解析视频流时）。
    解析失败的具体原因会写入视频日志，便于排查是视频本身无流、
    网络问题还是凭据失效，而不是被笼统吞掉。
    """
    if not has_ffmpeg():
        return None
    try:
        stream = video_stream_for_item(client, item)
    except (BilibiliAPIError, OSError) as exc:
        # 只捕获可预期的接口/网络错误；KeyboardInterrupt 等系统异常照常向上抛。
        # BilibiliAPIError: 视频无可用流 / 凭据问题；OSError 覆盖 URLError（其基类）。
        _write_video_log(f"解析视频流失败 [{type(exc).__name__}]: {exc}")
        return None
    player = VideoPlayer(stream, cols, rows, fps, video_key=_video_key_from_item(item))
    player.start()
    return player


def _video_key_from_item(item: "VideoItem") -> str | None:
    if item.bvid:
        return str(item.bvid)
    if item.aid is not None:
        return f"av{item.aid}"
    return str(item.url) if item.url else None
