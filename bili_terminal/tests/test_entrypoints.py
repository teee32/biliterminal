from __future__ import annotations

import tempfile
import unittest
from unittest import mock

from bili_terminal import __main__ as entry
from bili_terminal.macos import runtime_entry
from bili_terminal.tui.utils import load_tui_config, save_tui_config


class EntrypointAliasTests(unittest.TestCase):
    def test_tui_subcommand_routes_to_legacy_main(self) -> None:
        with mock.patch.object(entry, "legacy_main", return_value=0) as legacy_main:
            result = entry.main(["tui"])
        self.assertEqual(result, 0)
        legacy_main.assert_called_once_with(["tui"])

    def test_dash_tui_alias_routes_to_textual(self) -> None:
        with mock.patch.object(entry, "_run_textual", return_value=0) as run_textual:
            result = entry.main(["--tui"])
        self.assertEqual(result, 0)
        run_textual.assert_called_once_with([])

    def test_legacy_flag_routes_to_legacy_tui(self) -> None:
        with mock.patch.object(entry, "legacy_main", return_value=0) as legacy_main:
            result = entry.main(["--legacy-tui"])
        self.assertEqual(result, 0)
        legacy_main.assert_called_once_with(["tui"])

    def test_runtime_entry_defaults_to_textual_when_no_args(self) -> None:
        with mock.patch.object(runtime_entry, "main", return_value=0) as main:
            with mock.patch("sys.argv", ["BiliTerminal"]):
                result = runtime_entry.run()
        self.assertEqual(result, 0)
        main.assert_called_once_with(["--tui"])

    def test_runtime_entry_passes_through_explicit_args(self) -> None:
        with mock.patch.object(runtime_entry, "main", return_value=0) as main:
            with mock.patch("sys.argv", ["BiliTerminal", "recommend", "-n", "2"]):
                result = runtime_entry.run()
        self.assertEqual(result, 0)
        main.assert_called_once_with(["recommend", "-n", "2"])


class TuiConfigTests(unittest.TestCase):
    def test_load_tui_config_defaults_to_dark(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = load_tui_config(f"{temp_dir}/missing.toml")
        self.assertEqual(config.theme, "dark")

    def test_load_tui_config_reads_light_theme(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = f"{temp_dir}/config.toml"
            with open(path, "w", encoding="utf-8") as handle:
                handle.write('[ui]\ntheme = "light"\n')
            config = load_tui_config(path)
        self.assertEqual(config.theme, "light")

    def test_save_tui_config_persists_theme(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = f"{temp_dir}/config.toml"
            config = save_tui_config("light", path)
            self.assertEqual(config.theme, "light")
            self.assertEqual(load_tui_config(path).theme, "light")
