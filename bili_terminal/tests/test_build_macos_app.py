from __future__ import annotations

import os
import shutil
import stat
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


class BuildMacOSAppScriptTests(unittest.TestCase):
    def test_build_script_packages_textual_tree_and_legacy_entrypoints(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        package_root = repo_root / "bili_terminal"

        with tempfile.TemporaryDirectory() as tmpdir:
            temp_root = Path(tmpdir) / "repo"
            shutil.copytree(package_root, temp_root / "bili_terminal")

            fake_bin = temp_root / "fake-bin"
            fake_bin.mkdir()
            self._write_fake_command(
                fake_bin / "osacompile",
                """
                #!/bin/sh
                out=""
                while [ "$#" -gt 0 ]; do
                    if [ "$1" = "-o" ]; then
                        out="$2"
                        shift 2
                    else
                        shift
                    fi
                done
                mkdir -p "$out/Contents/Resources"
                """,
            )
            self._write_fake_command(
                fake_bin / "clang",
                """
                #!/bin/sh
                out=""
                while [ "$#" -gt 0 ]; do
                    if [ "$1" = "-o" ]; then
                        out="$2"
                        shift 2
                    else
                        shift
                    fi
                done
                : > "$out"
                """,
            )
            self._write_fake_command(
                fake_bin / "ditto",
                """
                #!/bin/sh
                for last_arg in "$@"; do :; done
                : > "$last_arg"
                """,
            )

            env = os.environ.copy()
            env["PATH"] = f"{fake_bin}:{env['PATH']}"

            script_path = temp_root / "bili_terminal" / "build_macos_app.sh"
            result = subprocess.run(
                ["bash", str(script_path)],
                cwd=temp_root,
                env=env,
                check=True,
                capture_output=True,
                text=True,
            )

            payload_dir = temp_root / "dist" / "BiliTerminal.app" / "Contents" / "Resources" / "app" / "bili_terminal"
            self.assertTrue((payload_dir / "__main__.py").is_file())
            self.assertTrue((payload_dir / "bilibili_cli.py").is_file())
            self.assertTrue((payload_dir / "macos" / "biliterminal_audio_helper.m").is_file())
            self.assertTrue((payload_dir / "biliterminal-audio-helper").is_file())
            self.assertTrue((temp_root / "dist" / "BiliTerminal-macOS.zip").is_file())

            expected_textual_files = {
                path.relative_to(package_root / "tui")
                for path in (package_root / "tui").rglob("*")
                if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"
            }
            packaged_textual_files = {
                path.relative_to(payload_dir / "tui")
                for path in (payload_dir / "tui").rglob("*")
                if path.is_file()
            }
            self.assertEqual(packaged_textual_files, expected_textual_files)
            self.assertFalse(any("__pycache__" in path.parts for path in (payload_dir / "tui").rglob("*")))
            self.assertIn("Built", result.stdout)
            self.assertIn("Packed", result.stdout)

    def _write_fake_command(self, path: Path, body: str) -> None:
        path.write_text(textwrap.dedent(body).lstrip(), encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
