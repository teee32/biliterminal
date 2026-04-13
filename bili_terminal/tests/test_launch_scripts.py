from __future__ import annotations

import os
import shutil
import stat
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


class ShellLaunchScriptTests(unittest.TestCase):
    def test_root_wrapper_defaults_to_legacy_tui(self) -> None:
        recorded = self._run_wrapper("biliterminal")
        self.assertEqual(recorded, ["-m", "bili_terminal", "--legacy-tui"])

    def test_root_wrapper_routes_dash_tui_to_textual(self) -> None:
        recorded = self._run_wrapper("biliterminal", "--tui")
        self.assertEqual(recorded, ["-m", "bili_terminal", "--tui"])

    def test_start_sh_routes_textual_keyword_to_textual_ui(self) -> None:
        recorded = self._run_wrapper("bili_terminal/start.sh", "textual")
        self.assertEqual(recorded, ["-m", "bili_terminal", "textual"])

    def test_start_sh_preserves_command_passthrough(self) -> None:
        recorded = self._run_wrapper("bili_terminal/start.sh", "recommend", "-n", "2")
        self.assertEqual(recorded, ["-m", "bili_terminal", "recommend", "-n", "2"])

    def _run_wrapper(self, relative_path: str, *args: str) -> list[str]:
        repo_root = Path(__file__).resolve().parents[2]
        wrapper_source = repo_root / relative_path

        with tempfile.TemporaryDirectory() as tmpdir:
            temp_root = Path(tmpdir) / "repo"
            target_wrapper = temp_root / relative_path
            target_wrapper.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(wrapper_source, target_wrapper)
            target_wrapper.chmod(target_wrapper.stat().st_mode | stat.S_IXUSR)

            fake_python = temp_root / ".venv" / "bin" / "python"
            fake_python.parent.mkdir(parents=True, exist_ok=True)
            argv_log = temp_root / "argv.log"
            fake_python.write_text(
                textwrap.dedent(
                    f"""\
                    #!/bin/sh
                    printf '%s\\n' \"$@\" > \"{argv_log}\"
                    """
                ),
                encoding="utf-8",
            )
            fake_python.chmod(fake_python.stat().st_mode | stat.S_IXUSR)

            env = os.environ.copy()
            env["PATH"] = f"{fake_python.parent}:{env['PATH']}"

            subprocess.run(
                ["bash", str(target_wrapper), *args],
                cwd=temp_root,
                env=env,
                check=True,
                text=True,
                capture_output=True,
            )

            return argv_log.read_text(encoding="utf-8").splitlines()


@unittest.skipUnless(os.name == "nt", "Windows batch wrappers only run on Windows")
class BatchLaunchScriptTests(unittest.TestCase):
    def test_package_start_bat_defaults_to_textual_ui(self) -> None:
        recorded = self._run_batch_wrapper("bili_terminal/start.bat")
        self.assertEqual(recorded, ["--tui"])

    def test_root_wrapper_defaults_to_textual_ui(self) -> None:
        recorded = self._run_batch_wrapper("biliterminal.bat")
        self.assertEqual(recorded, ["--tui"])

    def test_package_start_bat_preserves_command_passthrough(self) -> None:
        recorded = self._run_batch_wrapper(
            "bili_terminal/start.bat", "recommend", "-n", "2"
        )
        self.assertEqual(recorded, ["recommend", "-n", "2"])

    def _run_batch_wrapper(self, relative_path: str, *args: str) -> list[str]:
        repo_root = Path(__file__).resolve().parents[2]
        wrapper_source = repo_root / relative_path

        with tempfile.TemporaryDirectory() as tmpdir:
            temp_root = Path(tmpdir) / "repo"
            target_wrapper = temp_root / relative_path
            target_wrapper.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(wrapper_source, target_wrapper)

            package_dir = temp_root / "bili_terminal"
            package_dir.mkdir(parents=True, exist_ok=True)
            (package_dir / "__init__.py").write_text("", encoding="utf-8")
            argv_log = temp_root / "argv.log"
            (package_dir / "__main__.py").write_text(
                textwrap.dedent(
                    f"""\
                    import pathlib
                    import sys

                    pathlib.Path(r\"{argv_log}\").write_text("\\n".join(sys.argv[1:]), encoding="utf-8")
                    raise SystemExit(0)
                    """
                ),
                encoding="utf-8",
            )

            subprocess.run(
                ["cmd.exe", "/c", str(target_wrapper), *args],
                cwd=temp_root,
                check=True,
                text=True,
                capture_output=True,
            )

            return argv_log.read_text(encoding="utf-8").splitlines()
