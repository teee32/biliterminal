from __future__ import annotations

import importlib.util
import os
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

TEXTUAL_AVAILABLE = importlib.util.find_spec("textual") is not None

from bili_terminal import bilibili_cli as cli
from bili_terminal.tui import app as textual_app

if TEXTUAL_AVAILABLE:
    from textual.widgets import Input


class FakeClient:
    def __init__(self) -> None:
        self.items = [
            cli.VideoItem(
                title=f"测试视频 {index}",
                author=f"UP {index}",
                bvid=f"BV1xx411c7m{index}",
                aid=1000 + index,
                duration=f"{index}:0{index}",
                play=10000 * index,
                danmaku=100 * index,
                like=10 * index,
                favorite=5 * index,
                pubdate=1710000000 + index,
                description=f"这是第 {index} 个测试视频",
                url=f"https://www.bilibili.com/video/BV1xx411c7m{index}",
                raw={"pic": "https://i0.hdslb.com/bfs/archive/demo.jpg"},
            )
            for index in range(1, 4)
        ]

    def _page(self, page: int, page_size: int) -> list[cli.VideoItem]:
        start = max(0, page - 1) * page_size
        items = self.items * max(1, page_size)
        return items[start : start + page_size] or self.items[:page_size]

    def recommend(self, page: int = 1, page_size: int = 10) -> list[cli.VideoItem]:
        return self._page(page, page_size)

    def popular(self, page: int = 1, page_size: int = 10) -> list[cli.VideoItem]:
        return self._page(page, page_size)

    def precious(self, page: int = 1, page_size: int = 10) -> list[cli.VideoItem]:
        return self._page(page, page_size)

    def region_ranking(
        self, rid: int, day: int = 3, page: int = 1, page_size: int = 10
    ) -> list[cli.VideoItem]:
        return self._page(page, page_size)

    def bangumi(
        self,
        category: str = "番剧",
        *,
        index: bool = False,
        area: str | None = None,
        page: int = 1,
        page_size: int = 10,
    ) -> list[cli.VideoItem]:
        return self._page(page, page_size)

    def search(
        self, keyword: str, page: int = 1, page_size: int = 10
    ) -> list[cli.VideoItem]:
        return [item for item in self._page(page, page_size) if keyword or item.title]

    def video(self, ref: str) -> cli.VideoItem:
        for item in self.items:
            if ref in {item.bvid, str(item.aid), f"av{item.aid}"}:
                return item
        return self.items[0]

    def comments(
        self, oid: int, page_size: int = 4, bvid: str | None = None
    ) -> list[cli.CommentItem]:
        return [
            cli.CommentItem(
                author="热评用户", message="这是一条测试评论", like=42, ctime=1710000000
            ),
            cli.CommentItem(
                author="第二条", message="评论预览正常", like=7, ctime=1710000300
            ),
        ][:page_size]

    def search_default(self) -> str:
        return "默认搜索词"

    def trending_keywords(self, limit: int = 8) -> list[str]:
        return [f"热词{index}" for index in range(1, limit + 1)]


class TextualImportSmokeTests(unittest.TestCase):
    def test_create_app_exposes_metadata(self) -> None:
        app = textual_app.create_app()
        self.assertEqual(app.TITLE, "BiliTerminal")
        self.assertEqual(app.CSS_PATH, "styles/bili_dark.tcss")
        self.assertTrue(textual_app.LEGACY_KEYMAP_SUMMARY)

    def test_command_palette_is_enabled(self) -> None:
        app = textual_app.create_app()
        self.assertTrue(getattr(app, "ENABLE_COMMAND_PALETTE", False))

    def test_app_registers_legacy_keymap(self) -> None:
        app = textual_app.create_app()
        bindings = getattr(app, "BINDINGS", ())
        keys = {
            getattr(binding, "key", None)
            for binding in bindings
            if getattr(binding, "key", None)
        }
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

    def test_run_textual_app_reports_repo_root_install_command(self) -> None:
        repo_root = pathlib.Path(textual_app.__file__).resolve().parents[2]
        expected = (
            "Textual 依赖缺失，请先执行 `"
            f'"{sys.executable}" -m pip install -e "{repo_root}"`。'
        )
        with mock.patch.object(
            textual_app, "TEXTUAL_IMPORT_ERROR", ModuleNotFoundError("textual")
        ):
            with mock.patch("sys.stderr") as stderr:
                result = textual_app.run_textual_app()
        self.assertEqual(result, 1)
        written = "".join(call.args[0] for call in stderr.write.call_args_list)
        self.assertEqual(written, expected + "\n")


@unittest.skipUnless(TEXTUAL_AVAILABLE, "textual dependency not installed")
class TextualBootSmokeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.client = FakeClient()
        self.history_store = cli.HistoryStore(path=f"{self.temp_dir.name}/history.json")
        self.history_store.add_keyword("原神")
        self.history_store.add_video(self.client.items[0])
        self.history_store.add_favorite(self.client.items[1])

    def make_app(self):
        return textual_app.create_app(
            client=self.client, history_store=self.history_store
        )

    async def test_app_boots_headless(self) -> None:
        app = self.make_app()
        async with app.run_test(size=(120, 36)) as pilot:
            await pilot.pause()
            self.assertEqual(app.screen.__class__.__name__, "HomeScreen")
            self.assertIsNotNone(app.screen.query_one("#channel-list"))
            self.assertIsNotNone(app.screen.query_one("#video-list"))
            self.assertIsNotNone(app.screen.query_one("#audio-bar"))

    async def test_zero_shortcut_jumps_to_tenth_channel(self) -> None:
        app = self.make_app()
        async with app.run_test(size=(120, 36)) as pilot:
            await pilot.press("0")
            await pilot.pause()
            self.assertEqual(getattr(app.screen, "channel_index", None), 9)

    async def test_search_detail_and_back_flow(self) -> None:
        app = self.make_app()
        async with app.run_test(size=(120, 36)) as pilot:
            await pilot.press("/")
            await pilot.pause()
            self.assertEqual(app.screen.__class__.__name__, "SearchScreen")
            search_screen = app.screen
            input_widget = search_screen.query_one("#search-input", Input)
            input_widget.value = "测试"
            await pilot.press("enter")
            await pilot.pause()
            self.assertEqual(getattr(search_screen, "keyword", ""), "测试")
            await pilot.press("enter")
            await pilot.pause()
            self.assertEqual(app.screen.__class__.__name__, "DetailScreen")
            await pilot.press("b")
            await pilot.pause()
            self.assertEqual(app.screen.__class__.__name__, "SearchScreen")
            await pilot.press("b")
            await pilot.pause()
            self.assertEqual(app.screen.__class__.__name__, "HomeScreen")

    async def test_history_and_favorites_shortcuts(self) -> None:
        app = self.make_app()
        async with app.run_test(size=(120, 36)) as pilot:
            await pilot.press("v")
            await pilot.pause()
            self.assertEqual(app.screen.__class__.__name__, "HistoryScreen")
            await pilot.press("b")
            await pilot.pause()
            await pilot.press("m")
            await pilot.pause()
            self.assertEqual(app.screen.__class__.__name__, "FavoritesScreen")

    async def test_theme_config_hot_reload_switches_screen_class(self) -> None:
        config_path = f"{self.temp_dir.name}/config.toml"
        with open(config_path, "w", encoding="utf-8") as handle:
            handle.write('[ui]\ntheme = "dark"\n')
        with mock.patch.dict(
            os.environ, {"BILITERMINAL_CONFIG": config_path}, clear=False
        ):
            app = self.make_app()
            async with app.run_test(size=(120, 36)) as pilot:
                await pilot.pause()
                self.assertFalse(app.screen.has_class("theme-light"))
                dark_status_background = str(
                    app.screen.query_one("#status-line").styles.background
                )
                with open(config_path, "w", encoding="utf-8") as handle:
                    handle.write('[ui]\ntheme = "light"\n')
                app._poll_config()
                await pilot.pause()
                self.assertTrue(app.screen.has_class("theme-light"))
                light_status_background = str(
                    app.screen.query_one("#status-line").styles.background
                )
                self.assertNotEqual(dark_status_background, light_status_background)

    async def test_ctrl_t_toggles_theme_and_persists_config(self) -> None:
        config_path = f"{self.temp_dir.name}/config.toml"
        with open(config_path, "w", encoding="utf-8") as handle:
            handle.write('[ui]\ntheme = "dark"\n')
        with mock.patch.dict(
            os.environ, {"BILITERMINAL_CONFIG": config_path}, clear=False
        ):
            app = self.make_app()
            async with app.run_test(size=(120, 36)) as pilot:
                await pilot.pause()
                dark_status_background = str(
                    app.screen.query_one("#status-line").styles.background
                )
                dark_layout_background = str(
                    app.screen.query_one("#browser-layout").styles.background
                )
                self.assertFalse(app.screen.has_class("theme-light"))
                await pilot.press("ctrl+t")
                await pilot.pause()
                self.assertTrue(app.screen.has_class("theme-light"))
                await pilot.press("f2")
                await pilot.pause()
                self.assertFalse(app.screen.has_class("theme-light"))
                await pilot.press("f2")
                await pilot.pause()
                self.assertTrue(app.screen.has_class("theme-light"))
                light_status_background = str(
                    app.screen.query_one("#status-line").styles.background
                )
                light_layout_background = str(
                    app.screen.query_one("#browser-layout").styles.background
                )
                self.assertNotEqual(dark_status_background, light_status_background)
                self.assertNotEqual(dark_layout_background, light_layout_background)
                with open(config_path, "r", encoding="utf-8") as handle:
                    self.assertIn('theme = "light"', handle.read())

    async def test_change_theme_action_opens_custom_theme_picker(self) -> None:
        config_path = f"{self.temp_dir.name}/config.toml"
        with open(config_path, "w", encoding="utf-8") as handle:
            handle.write('[ui]\ntheme = "dark"\n')
        with mock.patch.dict(
            os.environ, {"BILITERMINAL_CONFIG": config_path}, clear=False
        ):
            app = self.make_app()
            async with app.run_test(size=(120, 36)) as pilot:
                await pilot.pause()
                app.action_change_theme()
                await pilot.pause()
                self.assertEqual(app.screen.__class__.__name__, "ThemePickerScreen")
                await pilot.press("down")
                await pilot.pause()
                await pilot.press("enter")
                await pilot.pause()
                self.assertEqual(app.screen.__class__.__name__, "HomeScreen")
                self.assertTrue(app.screen.has_class("theme-light"))
                with open(config_path, "r", encoding="utf-8") as handle:
                    self.assertIn('theme = "light"', handle.read())

    async def test_theme_picker_supports_jk_navigation(self) -> None:
        config_path = f"{self.temp_dir.name}/config.toml"
        with open(config_path, "w", encoding="utf-8") as handle:
            handle.write('[ui]\ntheme = "dark"\n')
        with mock.patch.dict(
            os.environ, {"BILITERMINAL_CONFIG": config_path}, clear=False
        ):
            app = self.make_app()
            async with app.run_test(size=(120, 36)) as pilot:
                await pilot.pause()
                app.action_change_theme()
                await pilot.pause()
                self.assertEqual(app.screen.__class__.__name__, "ThemePickerScreen")
                await pilot.press("j")
                await pilot.pause()
                await pilot.press("enter")
                await pilot.pause()
                self.assertEqual(app.screen.__class__.__name__, "HomeScreen")
                self.assertTrue(app.screen.has_class("theme-light"))

    async def test_keys_system_command_uses_overlay_instead_of_help_panel(self) -> None:
        app = self.make_app()
        async with app.run_test(size=(120, 36)) as pilot:
            await pilot.pause()
            overlay = app.screen.query_one("#help-overlay")
            self.assertTrue(overlay.has_class("hidden"))
            keys_command = next(
                command
                for command in app.get_system_commands(app.screen)
                if command[0] == "Keys"
            )
            keys_command[2]()
            await pilot.pause()
            self.assertFalse(overlay.has_class("hidden"))
            self.assertFalse(
                any(
                    type(widget).__name__ == "HelpPanel"
                    for widget in app.screen.walk_children()
                )
            )
            keys_command = next(
                command
                for command in app.get_system_commands(app.screen)
                if command[0] == "Keys"
            )
            keys_command[2]()
            await pilot.pause()
            self.assertTrue(overlay.has_class("hidden"))

    async def test_command_palette_keys_escape_closes_overlay_without_blank_screen(
        self,
    ) -> None:
        app = self.make_app()
        async with app.run_test(size=(120, 36)) as pilot:
            await pilot.pause()
            self.assertEqual(app.screen.__class__.__name__, "HomeScreen")
            await pilot.press("ctrl+p")
            await pilot.pause()
            self.assertEqual(app.screen.__class__.__name__, "CommandPalette")
            await pilot.press("k", "e", "y", "s")
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            self.assertEqual(app.screen.__class__.__name__, "HomeScreen")
            overlay = app.screen.query_one("#help-overlay")
            self.assertFalse(overlay.has_class("hidden"))
            await pilot.press("escape")
            await pilot.pause()
            self.assertEqual(app.screen.__class__.__name__, "HomeScreen")
            self.assertTrue(app.screen.query_one("#help-overlay").has_class("hidden"))
            self.assertIsNotNone(app.screen.query_one("#video-list"))
            self.assertEqual(len(app.screen_stack), 2)
            self.assertFalse(
                any(
                    type(widget).__name__ == "HelpPanel"
                    for widget in app.screen.walk_children()
                )
            )

    async def test_theme_toggle_propagates_between_detail_and_home(self) -> None:
        config_path = f"{self.temp_dir.name}/config.toml"
        with open(config_path, "w", encoding="utf-8") as handle:
            handle.write('[ui]\ntheme = "dark"\n')
        with mock.patch.dict(
            os.environ, {"BILITERMINAL_CONFIG": config_path}, clear=False
        ):
            app = self.make_app()
            async with app.run_test(size=(120, 36)) as pilot:
                await pilot.pause()
                await pilot.press("enter")
                await pilot.pause()
                self.assertEqual(app.screen.__class__.__name__, "DetailScreen")
                self.assertFalse(app.screen.has_class("theme-light"))
                await pilot.press("ctrl+t")
                await pilot.pause()
                self.assertTrue(app.screen.has_class("theme-light"))
                self.assertEqual(
                    str(app.screen.query_one("#detail-scroll").styles.background),
                    "Color(255, 243, 248)",
                )
                await pilot.press("b")
                await pilot.pause()
                self.assertEqual(app.screen.__class__.__name__, "HomeScreen")
                self.assertTrue(app.screen.has_class("theme-light"))
                self.assertEqual(
                    str(app.screen.query_one("#channel-list").styles.background),
                    "Color(255, 243, 248)",
                )
