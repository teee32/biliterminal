from __future__ import annotations

import unittest

from bili_terminal.generate_readme_screenshots import APP_BOOT_COMMAND


class ReadmeScreenshotScriptTests(unittest.TestCase):
    def test_screenshot_boot_command_uses_textual_ui(self) -> None:
        self.assertEqual(APP_BOOT_COMMAND, "python3 -m bili_terminal --tui")
