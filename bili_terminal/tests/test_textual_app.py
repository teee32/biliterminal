from __future__ import annotations

import importlib.util
import unittest

TEXTUAL_AVAILABLE = importlib.util.find_spec("textual") is not None

from bili_terminal.tui import app as textual_app


class TextualImportSmokeTests(unittest.TestCase):
    def test_create_app_exposes_stage1_metadata(self) -> None:
        app = textual_app.create_app()
        self.assertEqual(app.TITLE, "BiliTerminal")
        self.assertEqual(app.CSS_PATH, "styles/bili_dark.tcss")
        self.assertTrue(textual_app.LEGACY_KEYMAP_SUMMARY)

    def test_app_registers_legacy_stage1_keymap(self) -> None:
        app = textual_app.create_app()
        bindings = getattr(app, "BINDINGS", ())
        keys = {getattr(binding, "key", None) for binding in bindings if getattr(binding, "key", None)}
        if not keys:
            self.skipTest("textual bindings unavailable in this interpreter")
        self.assertTrue(
            {
                "up",
                "down",
                "j",
                "k",
                "enter",
                "escape",
                "b",
                "slash",
                "s",
                "tab",
                "shift+tab",
                "l",
                "d",
                "h",
                "v",
                "m",
                "f",
                "a",
                "x",
                "n",
                "p",
                "pageup",
                "pagedown",
                "o",
                "c",
                "r",
                "question_mark",
                "q",
            }.issubset(keys)
        )

    def test_main_returns_error_without_textual_dependency(self) -> None:
        if TEXTUAL_AVAILABLE:
            self.skipTest("textual is installed in this interpreter")
        self.assertEqual(textual_app.main(), 1)


@unittest.skipUnless(TEXTUAL_AVAILABLE, "textual dependency not installed")
class TextualBootSmokeTests(unittest.IsolatedAsyncioTestCase):
    async def test_app_boots_headless(self) -> None:
        app = textual_app.create_app()
        async with app.run_test(size=(120, 36)) as pilot:
            await pilot.pause()
            self.assertEqual(app.screen.__class__.__name__, "HomeScreen")
            self.assertIsNotNone(app.screen.query_one("#channel-list"))
            self.assertIsNotNone(app.screen.query_one("#video-list"))
            self.assertIsNotNone(app.screen.query_one("#audio-bar"))

    async def test_zero_shortcut_jumps_to_tenth_channel(self) -> None:
        app = textual_app.create_app()
        async with app.run_test(size=(120, 36)) as pilot:
            await pilot.press("0")
            await pilot.pause()
            self.assertEqual(getattr(app.screen, "channel_index", None), 9)
