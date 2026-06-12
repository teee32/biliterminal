from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import TYPE_CHECKING

from .models import AudioPlaybackState, AudioStream, BilibiliAPIError, VideoItem, video_key_from_item
from .paths import default_state_dir
from .textutil import truncate_display

if TYPE_CHECKING:
    from .client import BilibiliClient

MACOS_AUDIO_HELPER_NAME = "biliterminal-audio-helper"


def build_audio_player_command(stream: AudioStream) -> list[str] | None:
    if shutil.which("mpv"):
        return [
            "mpv",
            "--no-video",
            "--force-window=no",
            f"--title={stream.title}",
            f"--referrer={stream.referer}",
            f"--user-agent={stream.user_agent}",
            stream.url,
        ]
    if shutil.which("ffplay"):
        return [
            "ffplay",
            "-nodisp",
            "-autoexit",
            "-loglevel",
            "warning",
            "-headers",
            f"Referer: {stream.referer}\r\nUser-Agent: {stream.user_agent}\r\n",
            stream.url,
        ]
    return None


def audio_worker_log_path() -> str:
    return os.path.join(default_state_dir(), "audio-playback.log")


def audio_playback_state_path() -> str:
    return os.path.join(default_state_dir(), "audio-playback.json")


def macos_audio_helper_source_path() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "macos", "biliterminal_audio_helper.m")


def macos_audio_helper_binary_path() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), MACOS_AUDIO_HELPER_NAME)


def macos_cached_audio_helper_path() -> str:
    return os.path.join(default_state_dir(), "bin", MACOS_AUDIO_HELPER_NAME)


def executable_file_exists(path: str) -> bool:
    return os.path.isfile(path) and os.access(path, os.X_OK)


def compile_macos_audio_helper(source_path: str, output_path: str) -> None:
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    command = [
        "clang",
        "-fobjc-arc",
        "-framework",
        "Foundation",
        "-framework",
        "AVFoundation",
        source_path,
        "-o",
        output_path,
    ]
    try:
        subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        raise BilibiliAPIError(exc.stderr.strip() or "macOS 音频 helper 编译失败") from exc
    os.chmod(output_path, 0o755)


def macos_audio_helper_path() -> str | None:
    if sys.platform != "darwin":
        return None

    configured_path = os.environ.get("BILITERMINAL_AUDIO_HELPER", "").strip()
    if configured_path:
        expanded = os.path.expanduser(configured_path)
        if executable_file_exists(expanded):
            return expanded

    bundled_path = macos_audio_helper_binary_path()
    if executable_file_exists(bundled_path):
        return bundled_path

    source_path = macos_audio_helper_source_path()
    cached_path = macos_cached_audio_helper_path()
    if not os.path.isfile(source_path) or shutil.which("clang") is None:
        return None

    needs_rebuild = not executable_file_exists(cached_path)
    if not needs_rebuild:
        try:
            needs_rebuild = os.path.getmtime(source_path) > os.path.getmtime(cached_path)
        except OSError:
            needs_rebuild = True
    if needs_rebuild:
        try:
            compile_macos_audio_helper(source_path, cached_path)
        except BilibiliAPIError:
            if not executable_file_exists(cached_path):
                return None
    return cached_path if executable_file_exists(cached_path) else None


def pid_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def save_audio_playback_state(state: AudioPlaybackState) -> None:
    path = audio_playback_state_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(
            {
                "pid": state.pid,
                "title": state.title,
                "video_key": state.video_key,
                "backend": state.backend,
                "paused": state.paused,
                "control_pid": state.control_pid,
                "media_path": state.media_path,
            },
            handle,
            ensure_ascii=False,
            indent=2,
        )


def clear_audio_playback_state() -> None:
    try:
        os.unlink(audio_playback_state_path())
    except FileNotFoundError:
        return


def cleanup_audio_media_path(media_path: str | None) -> None:
    if not media_path:
        return
    try:
        os.unlink(media_path)
    except (FileNotFoundError, OSError):
        return


def load_audio_playback_state() -> AudioPlaybackState | None:
    path = audio_playback_state_path()
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None

    if not isinstance(payload, dict):
        clear_audio_playback_state()
        return None

    try:
        pid_value = payload.get("pid")
        state = AudioPlaybackState(
            pid=int(pid_value) if pid_value not in (None, "") else None,
            title=str(payload.get("title") or "当前音频"),
            video_key=payload.get("video_key"),
            backend=str(payload.get("backend") or "process"),
            paused=bool(payload.get("paused")),
            control_pid=int(payload["control_pid"]) if payload.get("control_pid") not in (None, "") else None,
            media_path=str(payload["media_path"]) if payload.get("media_path") else None,
        )
    except (KeyError, TypeError, ValueError):
        cleanup_audio_media_path(payload.get("media_path"))
        clear_audio_playback_state()
        return None

    if state.pid is None or not pid_exists(state.pid):
        cleanup_audio_media_path(state.media_path)
        clear_audio_playback_state()
        return None
    if state.control_pid is not None and not pid_exists(state.control_pid):
        # 播放器子进程已死但 worker 还活着，只在内存里丢弃失效的 control_pid；
        # 不回写文件，避免与 worker 的状态写入产生竞争
        state.control_pid = None
    return state


def send_audio_signal(pid: int, sig: int) -> None:
    os.kill(pid, sig)


def wait_for_audio_exit(pid: int, timeout: float = 1.5) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not pid_exists(pid):
            return
        time.sleep(0.05)


def pause_signal_for_state(state: AudioPlaybackState) -> int:
    return signal.SIGUSR1 if state.backend == "macos-native" else signal.SIGSTOP


def resume_signal_for_state(state: AudioPlaybackState) -> int:
    return signal.SIGUSR2 if state.backend == "macos-native" else signal.SIGCONT


def audio_control_target(state: AudioPlaybackState) -> int | None:
    return state.control_pid or state.pid


def _terminate_pid(pid: int, *, wake_first: bool, timeout: float, escalate: bool = False) -> None:
    if not pid_exists(pid):
        return
    try:
        if wake_first:
            # SIGSTOP 挂起的进程收不到 SIGTERM，先 SIGCONT 唤醒
            try:
                send_audio_signal(pid, signal.SIGCONT)
            except ProcessLookupError:
                return
        send_audio_signal(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    wait_for_audio_exit(pid, timeout)
    if escalate and pid_exists(pid):
        try:
            send_audio_signal(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass


def stop_audio_playback(*, silent: bool = False) -> str:
    state = load_audio_playback_state()
    if state is None:
        if silent:
            return ""
        raise BilibiliAPIError("当前没有音频在播放")
    wake_first = state.backend == "process" and state.paused
    try:
        if state.control_pid:
            _terminate_pid(state.control_pid, wake_first=wake_first, timeout=0.6)
        if state.pid is not None:
            _terminate_pid(state.pid, wake_first=False, timeout=1.5, escalate=True)
    except PermissionError:
        pass
    finally:
        cleanup_audio_media_path(state.media_path)
        clear_audio_playback_state()
    return f"已停止音频: {truncate_display(state.title, 40)}"


def pause_audio_playback() -> str:
    if os.name == "nt":
        raise BilibiliAPIError("当前平台不支持暂停音频，请直接停止后重播")
    state = load_audio_playback_state()
    if state is None:
        raise BilibiliAPIError("当前没有音频在播放")
    if state.paused:
        return f"音频已暂停: {truncate_display(state.title, 40)}"
    try:
        target_pid = audio_control_target(state)
        if target_pid is None:
            raise ProcessLookupError
        send_audio_signal(target_pid, pause_signal_for_state(state))
    except ProcessLookupError as exc:
        cleanup_audio_media_path(state.media_path)
        clear_audio_playback_state()
        raise BilibiliAPIError("当前没有音频在播放") from exc
    state.paused = True
    save_audio_playback_state(state)
    return f"已暂停音频: {truncate_display(state.title, 40)}"


def resume_audio_playback() -> str:
    if os.name == "nt":
        raise BilibiliAPIError("当前平台不支持继续音频，请直接重播")
    state = load_audio_playback_state()
    if state is None:
        raise BilibiliAPIError("当前没有音频在播放")
    if not state.paused:
        return f"音频播放中: {truncate_display(state.title, 40)}"
    try:
        target_pid = audio_control_target(state)
        if target_pid is None:
            raise ProcessLookupError
        send_audio_signal(target_pid, resume_signal_for_state(state))
    except ProcessLookupError as exc:
        cleanup_audio_media_path(state.media_path)
        clear_audio_playback_state()
        raise BilibiliAPIError("当前没有音频在播放") from exc
    state.paused = False
    save_audio_playback_state(state)
    return f"已继续播放音频: {truncate_display(state.title, 40)}"


def toggle_audio_playback() -> str:
    state = load_audio_playback_state()
    if state is None:
        raise BilibiliAPIError("当前没有音频在播放")
    if state.paused:
        return resume_audio_playback()
    return pause_audio_playback()


def spawn_audio_worker(stream: AudioStream, video_key: str | None) -> int:
    log_path = audio_worker_log_path()
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    command = [
        sys.executable,
        "-m",
        "bili_terminal",
        "audio-worker",
        "--url",
        stream.url,
        "--referer",
        stream.referer,
        "--user-agent",
        stream.user_agent,
        "--title",
        stream.title,
    ]
    if video_key:
        command.extend(["--video-key", video_key])
    env = dict(os.environ)
    package_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env["PYTHONPATH"] = package_root + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    with open(log_path, "ab") as log_handle:
        process = subprocess.Popen(
            command,
            stdout=log_handle,
            stderr=log_handle,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            env=env,
        )
    return process.pid


def play_audio_stream(stream: AudioStream, *, video_key: str | None = None) -> str:
    command = build_audio_player_command(stream)
    if command is None and macos_audio_helper_path() is None and not (sys.platform == "darwin" and shutil.which("afplay")):
        raise BilibiliAPIError("未找到可用播放器，请安装 mpv 或 ffplay")

    stop_audio_playback(silent=True)
    # 先写乐观状态让连按 a 能立即识别为同一视频的 toggle；
    # worker 启动需要完整 Python 解释器启动时间，必然晚于这次写入，
    # 之后由 worker（携带 --video-key）以权威状态覆盖
    pid = spawn_audio_worker(stream, video_key)
    save_audio_playback_state(
        AudioPlaybackState(
            pid=pid,
            title=stream.title,
            video_key=video_key,
            paused=False,
            control_pid=None,
        )
    )
    if command:
        return f"已开始播放音频: {truncate_display(stream.title, 40)}"
    return f"正在准备音频播放: {truncate_display(stream.title, 40)}"


def prepare_audio_temp_path(url: str) -> str:
    suffix = os.path.splitext(urllib.parse.urlparse(url).path)[1] or ".m4a"
    temp_file = tempfile.NamedTemporaryFile(prefix="biliterminal-audio-", suffix=suffix, delete=False)
    temp_path = temp_file.name
    temp_file.close()
    return temp_path


def download_audio_to_path(url: str, referer: str, user_agent: str, temp_path: str) -> None:
    try:
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": user_agent,
                "Accept": "*/*",
                "Referer": referer,
            },
        )
        with urllib.request.urlopen(request, timeout=60) as response, open(temp_path, "wb") as handle:
            while True:
                chunk = response.read(256 * 1024)
                if not chunk:
                    break
                handle.write(chunk)
    except urllib.error.HTTPError as exc:
        cleanup_audio_media_path(temp_path)
        raise BilibiliAPIError(f"音频下载失败 HTTP {exc.code}: {exc.reason}") from exc
    except urllib.error.URLError as exc:
        cleanup_audio_media_path(temp_path)
        raise BilibiliAPIError(f"音频下载失败: {exc.reason}") from exc


def play_audio_for_item(client: "BilibiliClient", item: VideoItem) -> str:
    stream = client.audio_stream_for_item(item)
    return play_audio_stream(stream, video_key=video_key_from_item(item))


def audio_action_for_item(client: "BilibiliClient", item: VideoItem) -> str:
    state = load_audio_playback_state()
    item_key = video_key_from_item(item)
    if state and state.video_key and item_key == state.video_key:
        return toggle_audio_playback()
    return play_audio_for_item(client, item)


def _resolve_worker_video_key(video_key: str | None) -> str | None:
    if video_key:
        return video_key
    existing_state = load_audio_playback_state()
    return existing_state.video_key if existing_state else None


def run_audio_worker(url: str, referer: str, user_agent: str, title: str, video_key: str | None = None) -> int:
    stream = AudioStream(title=title or "当前音频", url=url, referer=referer, user_agent=user_agent, source_kind="worker")
    resolved_key = _resolve_worker_video_key(video_key)
    command = build_audio_player_command(stream)
    if command:
        process = subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
        )
        save_audio_playback_state(
            AudioPlaybackState(
                pid=os.getpid(),
                title=stream.title,
                video_key=resolved_key,
                backend="process",
                paused=False,
                control_pid=process.pid,
            )
        )
        return process.wait()

    helper_path = macos_audio_helper_path()
    if helper_path:
        temp_path = prepare_audio_temp_path(url)
        try:
            save_audio_playback_state(
                AudioPlaybackState(
                    pid=os.getpid(),
                    title=stream.title,
                    video_key=resolved_key,
                    backend="macos-native",
                    paused=False,
                    control_pid=None,
                    media_path=temp_path,
                )
            )
            download_audio_to_path(url, referer, user_agent, temp_path)
            process = subprocess.Popen(
                [helper_path, temp_path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
            )
            save_audio_playback_state(
                AudioPlaybackState(
                    pid=os.getpid(),
                    title=stream.title,
                    video_key=resolved_key,
                    backend="macos-native",
                    paused=False,
                    control_pid=process.pid,
                    media_path=temp_path,
                )
            )
            return process.wait()
        finally:
            cleanup_audio_media_path(temp_path)

    if shutil.which("afplay") is None:
        raise BilibiliAPIError("当前系统没有 afplay，无法执行音频下载兜底播放")

    temp_path = prepare_audio_temp_path(url)
    try:
        save_audio_playback_state(
            AudioPlaybackState(
                pid=os.getpid(),
                title=stream.title,
                video_key=resolved_key,
                backend="afplay",
                paused=False,
                media_path=temp_path,
            )
        )
        download_audio_to_path(url, referer, user_agent, temp_path)
        process = subprocess.Popen(
            ["afplay", temp_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
        )
        save_audio_playback_state(
            AudioPlaybackState(
                pid=os.getpid(),
                title=stream.title,
                video_key=resolved_key,
                backend="afplay",
                paused=False,
                control_pid=process.pid,
                media_path=temp_path,
            )
        )
        return process.wait()
    finally:
        cleanup_audio_media_path(temp_path)
