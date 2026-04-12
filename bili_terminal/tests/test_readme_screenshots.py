from __future__ import annotations

import unittest

from bili_terminal.generate_readme_screenshots import APP_BOOT_COMMAND, SCREENSHOT_CONFIG


class ReadmeScreenshotScriptTests(unittest.TestCase):
    def test_screenshot_boot_command_uses_textual_ui(self) -> None:
        self.assertIn("-m bili_terminal --tui", APP_BOOT_COMMAND)
        self.assertIn(f"BILITERMINAL_CONFIG={SCREENSHOT_CONFIG}", APP_BOOT_COMMAND)
