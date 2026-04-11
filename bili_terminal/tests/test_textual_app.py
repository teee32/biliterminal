from __future__ import annotations

import importlib.util
import unittest

TEXTUAL_AVAILABLE = importlib.util.find_spec("textual") is not None

from bili_terminal.tui import app as textual_app


class TextualImportSmokeTests(unittest.TestCase):
    def test_create_app_exposes_stage1_metadata(self) -> None:
        app = textual_app.create_app()
        self.assertEqual(app.TITLE, "BiliTerminal")
        self.assertEqual(app.CSS_PATH, "styles.tcss")
        self.assertTrue(textual_app.LEGACY_KEYMAP_SUMMARY)

    def test_main_returns_error_without_textual_dependency(self) -> None:
        if TEXTUAL_AVAILABLE:
            self.skipTest("textual is installed; boot path is covered by async smoke test")
        self.assertEqual(textual_app.main(), 1)


@unittest.skipUnless(TEXTUAL_AVAILABLE, "textual extra not installed")
class TextualBootSmokeTests(unittest.IsolatedAsyncioTestCase):
    async def test_app_boots_headless(self) -> None:
        app = textual_app.create_app()
        async with app.run_test(size=(120, 36)) as pilot:
            await pilot.pause()
            hero = app.screen.query_one("#hero-title")
            status = app.screen.query_one("#status-line")
            hero_text = getattr(hero.renderable, "plain", str(hero.renderable))
            status_text = getattr(status.renderable, "plain", str(status.renderable))
            self.assertEqual(hero_text, "BiliTerminal · Textual v0.3.0 phase-1")
            self.assertIn("状态：", status_text)
