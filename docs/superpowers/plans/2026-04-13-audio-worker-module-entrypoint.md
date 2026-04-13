# Audio Worker Module Entrypoint Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix Windows audio playback so the worker launches successfully and actual audio reaches `ffplay`/`mpv` instead of failing before playback starts.

**Architecture:** Keep the existing worker-based playback design, state file handling, and platform audio control intact. Only change the Python worker launch path from direct script execution to package module execution so relative imports keep working in installed and editable environments.

**Tech Stack:** Python 3.11+, `unittest`, subprocess-based audio worker, `ffplay` / `mpv`

---

## File Map

- Modify: `bili_terminal/bilibili_cli.py`
  - Update `audio_worker_command()` so non-frozen environments launch `python -m bili_terminal ...` instead of running `bilibili_cli.py` as a script.
- Modify: `bili_terminal/tests/test_bilibili_cli.py`
  - Replace the old script-path expectation with module-entrypoint expectations and keep the frozen executable behavior unchanged.

### Task 1: Lock the Worker Command Contract with Tests

**Files:**
- Modify: `bili_terminal/tests/test_bilibili_cli.py:47-75`
- Test: `bili_terminal/tests/test_bilibili_cli.py`

- [ ] **Step 1: Write the failing test expectation for module launch**

```python
    def test_audio_worker_command_uses_module_entrypoint_when_not_frozen(self) -> None:
        stream = cli.AudioStream(
            title="标题",
            url="https://example.com/audio.m4s",
            referer="https://www.bilibili.com/video/BV1xx411c7mu",
            user_agent="UA",
            source_kind="dash-audio",
        )
        with (
            mock.patch.object(cli.sys, "executable", "/tmp/python"),
            mock.patch.object(cli.sys, "frozen", False, create=True),
        ):
            command = cli.audio_worker_command(stream)
        self.assertEqual(
            command,
            [
                "/tmp/python",
                "-m",
                "bili_terminal",
                "audio-worker",
                "--url",
                stream.url,
                "--referer",
                stream.referer,
                "--user-agent",
                "UA",
                "--title",
                "标题",
            ],
        )
```

- [ ] **Step 2: Run the focused test to verify it fails for the right reason**

Run: `python -m unittest "bili_terminal.tests.test_bilibili_cli.FormattingTests.test_audio_worker_command_uses_module_entrypoint_when_not_frozen"`

Expected: FAIL because the current command still contains the script path instead of `-m bili_terminal`.

- [ ] **Step 3: Keep the frozen executable expectation unchanged**

```python
    def test_audio_worker_command_uses_frozen_executable_without_script_path(
        self,
    ) -> None:
        stream = cli.AudioStream(
            title="标题",
            url="https://example.com/audio.m4s",
            referer="https://www.bilibili.com/video/BV1xx411c7mu",
            user_agent="UA",
            source_kind="dash-audio",
        )
        with (
            mock.patch.object(
                cli.sys,
                "executable",
                "/Applications/BiliTerminal.app/Contents/Resources/runtime/BiliTerminal",
            ),
            mock.patch.object(cli.sys, "frozen", True, create=True),
        ):
            command = cli.audio_worker_command(stream)
        self.assertEqual(
            command,
            [
                "/Applications/BiliTerminal.app/Contents/Resources/runtime/BiliTerminal",
                "audio-worker",
                "--url",
                stream.url,
                "--referer",
                stream.referer,
                "--user-agent",
                "UA",
                "--title",
                "标题",
            ],
        )
```

- [ ] **Step 4: Re-run both worker command tests before implementation**

Run: `python -m unittest "bili_terminal.tests.test_bilibili_cli.FormattingTests.test_audio_worker_command_uses_module_entrypoint_when_not_frozen" "bili_terminal.tests.test_bilibili_cli.FormattingTests.test_audio_worker_command_uses_frozen_executable_without_script_path"`

Expected:
- first test FAILS with the old script path
- second test PASSES unchanged

- [ ] **Step 5: Commit the failing-test change**

```bash
git add "bili_terminal/tests/test_bilibili_cli.py"
git commit -m "test: cover module-based audio worker launch"
```

### Task 2: Switch the Worker to Module Execution

**Files:**
- Modify: `bili_terminal/bilibili_cli.py:1055-1072`
- Test: `bili_terminal/tests/test_bilibili_cli.py`

- [ ] **Step 1: Update `audio_worker_command()` with the minimal non-frozen change**

```python
def audio_worker_command(stream: AudioStream) -> list[str]:
    command = [sys.executable]
    if not getattr(sys, "frozen", False):
        command.extend(["-m", "bili_terminal"])
    command.extend(
        [
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
    )
    return command
```

- [ ] **Step 2: Run the focused worker command tests to verify green**

Run: `python -m unittest "bili_terminal.tests.test_bilibili_cli.FormattingTests.test_audio_worker_command_uses_module_entrypoint_when_not_frozen" "bili_terminal.tests.test_bilibili_cli.FormattingTests.test_audio_worker_command_uses_frozen_executable_without_script_path"`

Expected: both tests PASS.

- [ ] **Step 3: Run the broader audio/platform regression tests**

Run: `python -m unittest "bili_terminal.tests.test_platform_audio" "bili_terminal.tests.test_launch_scripts.BatchLaunchScriptTests" "bili_terminal.tests.test_entrypoints"`

Expected: all listed tests PASS.

- [ ] **Step 4: Verify the original failure mode is gone from the worker log**

Run: `python -c "from bili_terminal.bilibili_cli import audio_worker_command, AudioStream; print(audio_worker_command(AudioStream(title='t', url='https://example.com/a.m4s', referer='https://www.bilibili.com', user_agent='UA', source_kind='worker')))"`

Expected: printed command starts with `[sys.executable, '-m', 'bili_terminal', 'audio-worker', ...]` and no longer references `bilibili_cli.py`.

- [ ] **Step 5: Manual Windows smoke check with real playback**

Run the app in Windows Terminal, start audio for one video, then inspect the worker log:

```bash
python -c "from bili_terminal.bilibili_cli import audio_worker_log_path; print(audio_worker_log_path())"
```

Expected:
- no `ImportError: attempted relative import with no known parent package`
- `ffplay` or `mpv` process stays alive while audio is playing
- the UI state `音频播放中` now matches audible playback

- [ ] **Step 6: Commit the production fix**

```bash
git add "bili_terminal/bilibili_cli.py" "bili_terminal/tests/test_bilibili_cli.py"
git commit -m "fix: launch audio worker as package module"
```

## Self-Review

- Spec coverage: the plan covers the approved minimal fix only, with no unrelated refactor.
- Placeholder scan: every code-edit step contains exact code and every verification step contains an exact command.
- Type consistency: `audio_worker_command`, `AudioStream`, and existing test class names all match current code.
