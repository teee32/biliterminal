from __future__ import annotations

import os
import signal
import unittest
from unittest import mock

from bili_terminal import platform_audio


class TestPlatformAudioDispatch(unittest.TestCase):
    def test_dispatches_to_correct_module(self) -> None:
        if os.name == "nt":
            from bili_terminal import platform_audio_nt as impl
        else:
            from bili_terminal import platform_audio_posix as impl
        self.assertIs(platform_audio.pid_exists, impl.pid_exists)
        self.assertIs(platform_audio.send_signal, impl.send_signal)
        self.assertIs(platform_audio.pause_process, impl.pause_process)
        self.assertIs(platform_audio.resume_process, impl.resume_process)
        self.assertIs(platform_audio.terminate_process, impl.terminate_process)
        self.assertIs(platform_audio.kill_process, impl.kill_process)
        self.assertIs(platform_audio.has_pause_resume, impl.has_pause_resume)


class TestPosixImplementation(unittest.TestCase):
    def setUp(self) -> None:
        if os.name == "nt":
            self.skipTest("POSIX tests only run on non-Windows platforms")
        from bili_terminal import platform_audio_posix as posix

        self.posix = posix

    def test_pid_exists_returns_true_for_current_process(self) -> None:
        self.assertTrue(self.posix.pid_exists(os.getpid()))

    def test_pid_exists_returns_false_for_nonexistent_pid(self) -> None:
        self.assertFalse(self.posix.pid_exists(999999999))

    def test_suspend_resume_signals_are_posix_signals(self) -> None:
        self.assertEqual(self.posix.suspend_signal(), signal.SIGSTOP)
        self.assertEqual(self.posix.resume_signal(), signal.SIGCONT)

    def test_has_pause_resume_returns_true(self) -> None:
        self.assertTrue(self.posix.has_pause_resume())

    def test_send_signal_delegates_to_os_kill(self) -> None:
        with mock.patch("os.kill") as mock_kill:
            self.posix.send_signal(1234, signal.SIGTERM)
            mock_kill.assert_called_once_with(1234, signal.SIGTERM)


class TestNtImplementation(unittest.TestCase):
    def setUp(self) -> None:
        if os.name != "nt":
            self.skipTest("NT tests only run on Windows platforms")
        from bili_terminal import platform_audio_nt as nt_mod

        self.nt = nt_mod

    def test_pid_exists_current_process(self) -> None:
        self.assertTrue(self.nt.pid_exists(os.getpid()))

    def test_pid_exists_nonexistent_pid(self) -> None:
        self.assertFalse(self.nt.pid_exists(999999999))

    def test_suspend_resume_signals_return_sentinels(self) -> None:
        self.assertEqual(self.nt.suspend_signal(), 0)
        self.assertEqual(self.nt.resume_signal(), 0)

    def test_has_pause_resume_returns_true(self) -> None:
        self.assertTrue(self.nt.has_pause_resume())

    def test_terminate_process_kills_nonexistent(self) -> None:
        with self.assertRaises(ProcessLookupError):
            self.nt.terminate_process(999999999)


class TestNtImplementationMocked(unittest.TestCase):
    def test_pause_process_calls_ntsuspend(self) -> None:
        from bili_terminal import platform_audio_nt as nt_mod

        mock_handle = 0x1234
        with (
            mock.patch.object(
                nt_mod._kernel32, "OpenProcess", return_value=mock_handle
            ) as mock_open,
            mock.patch.object(
                nt_mod._ntdll, "NtSuspendProcess", return_value=0
            ) as mock_suspend,
            mock.patch.object(
                nt_mod._kernel32, "CloseHandle", return_value=1
            ) as mock_close,
        ):
            nt_mod.pause_process(42)
            mock_open.assert_called_once_with(nt_mod._PROCESS_SUSPEND_RESUME, False, 42)
            mock_suspend.assert_called_once_with(mock_handle)
            mock_close.assert_called_once_with(mock_handle)

    def test_resume_process_calls_ntresume(self) -> None:
        from bili_terminal import platform_audio_nt as nt_mod

        mock_handle = 0x5678
        with (
            mock.patch.object(
                nt_mod._kernel32, "OpenProcess", return_value=mock_handle
            ) as mock_open,
            mock.patch.object(
                nt_mod._ntdll, "NtResumeProcess", return_value=0
            ) as mock_resume,
            mock.patch.object(
                nt_mod._kernel32, "CloseHandle", return_value=1
            ) as mock_close,
        ):
            nt_mod.resume_process(42)
            mock_open.assert_called_once_with(nt_mod._PROCESS_SUSPEND_RESUME, False, 42)
            mock_resume.assert_called_once_with(mock_handle)
            mock_close.assert_called_once_with(mock_handle)

    def test_terminate_process_calls_terminateprocess(self) -> None:
        from bili_terminal import platform_audio_nt as nt_mod

        mock_handle = 0xABCD
        with (
            mock.patch.object(
                nt_mod._kernel32, "OpenProcess", return_value=mock_handle
            ),
            mock.patch.object(nt_mod._kernel32, "TerminateProcess", return_value=1),
            mock.patch.object(nt_mod._kernel32, "CloseHandle", return_value=1),
        ):
            nt_mod.terminate_process(42)

    def test_kill_process_calls_terminate(self) -> None:
        from bili_terminal import platform_audio_nt as nt_mod

        with mock.patch.object(nt_mod, "terminate_process") as mock_term:
            nt_mod.kill_process(42)
            mock_term.assert_called_once_with(42)


class TestBilibiliCliPlatformIntegration(unittest.TestCase):
    def test_pause_audio_playback_uses_platform_pause(self) -> None:
        from bili_terminal.bilibili_cli import (
            AudioPlaybackState,
            pause_audio_playback,
        )

        state = AudioPlaybackState(
            pid=1234,
            title="test",
            video_key="BV1xx411c7mu",
            backend="process",
            paused=False,
        )
        with (
            mock.patch(
                "bili_terminal.bilibili_cli.load_audio_playback_state",
                return_value=state,
            ),
            mock.patch.object(platform_audio, "pause_process") as mock_pause,
        ):
            result = pause_audio_playback()
            mock_pause.assert_called_once_with(1234)
            self.assertIn("已暂停", result)

    def test_resume_audio_playback_uses_platform_resume(self) -> None:
        from bili_terminal.bilibili_cli import (
            AudioPlaybackState,
            resume_audio_playback,
        )

        state = AudioPlaybackState(
            pid=1234,
            title="test",
            video_key="BV1xx411c7mu",
            backend="process",
            paused=True,
        )
        with (
            mock.patch(
                "bili_terminal.bilibili_cli.load_audio_playback_state",
                return_value=state,
            ),
            mock.patch.object(platform_audio, "resume_process") as mock_resume,
            mock.patch("bili_terminal.bilibili_cli.save_audio_playback_state"),
        ):
            result = resume_audio_playback()
            mock_resume.assert_called_once_with(1234)
            self.assertIn("已继续播放", result)

    def test_pause_keeps_macos_native_signal_path(self) -> None:
        from bili_terminal.bilibili_cli import (
            AudioPlaybackState,
            pause_audio_playback,
            send_audio_signal,
        )

        state = AudioPlaybackState(
            pid=4321,
            title="test",
            video_key="BV1xx411c7mu",
            backend="macos-native",
            paused=False,
            control_pid=8765,
        )
        sigusr1 = getattr(signal, "SIGUSR1", None)
        if sigusr1 is None:
            self.skipTest("SIGUSR1 not available on this platform")
        with (
            mock.patch(
                "bili_terminal.bilibili_cli.load_audio_playback_state",
                return_value=state,
            ),
            mock.patch.object(platform_audio, "pause_process") as mock_pause,
            mock.patch("bili_terminal.bilibili_cli.send_audio_signal") as mock_signal,
            mock.patch("bili_terminal.bilibili_cli.save_audio_playback_state"),
        ):
            pause_audio_playback()
            mock_signal.assert_called_once_with(8765, sigusr1)
            mock_pause.assert_not_called()

    def test_stop_uses_platform_terminate_and_kill(self) -> None:
        from bili_terminal.bilibili_cli import (
            AudioPlaybackState,
            stop_audio_playback,
        )

        state = AudioPlaybackState(
            pid=4321,
            title="test",
            video_key="BV1xx411c7mu",
            backend="process",
            paused=False,
        )
        with (
            mock.patch(
                "bili_terminal.bilibili_cli.load_audio_playback_state",
                return_value=state,
            ),
            mock.patch.object(
                platform_audio, "pid_exists", side_effect=[True, True, False]
            ),
            mock.patch.object(platform_audio, "terminate_process") as mock_term,
            mock.patch("bili_terminal.bilibili_cli.wait_for_audio_exit"),
        ):
            stop_audio_playback(silent=True)
            mock_term.assert_called_once_with(4321)


if __name__ == "__main__":
    unittest.main()
