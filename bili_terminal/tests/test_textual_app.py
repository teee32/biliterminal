from __future__ import annotations

import ast
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

TEXTUAL_AVAILABLE = importlib.util.find_spec("textual") is not None

from bili_terminal import core
from bili_terminal.tui import app as textual_app
from bili_terminal.tui import keymap as tui_keymap
from bili_terminal.tui.utils import TextualAdapter
from bili_terminal.tui.utils import (
    DEFAULT_COMMENT_PANEL_TITLE,
    DEFAULT_COMMENT_PREVIEW_EMPTY_MESSAGE,
    DEFAULT_DEFAULT_SEARCH_LOAD_FAILED_PREFIX,
    DEFAULT_EMPTY_RECENT_SEARCHES_TEXT,
    DEFAULT_NO_DEFAULT_SEARCH_STATUS,
    DEFAULT_NO_VISIBLE_VIDEO_MESSAGE,
    DEFAULT_NO_RECENT_SEARCH_STATUS,
    DEFAULT_SEARCH_PLACEHOLDER,
    format_no_video_status,
    format_help_overlay_status,
    format_search_title,
    format_status_text,
    format_theme_status_message,
    format_recent_searches_text,
    help_text,
    theme_label,
)

if TEXTUAL_AVAILABLE:
    from textual.widgets import Input


class FakeClient:
    def __init__(self) -> None:
        self.items = [
            core.VideoItem(
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

    def _page(self, page: int, page_size: int) -> list[core.VideoItem]:
        start = max(0, page - 1) * page_size
        items = self.items * max(1, page_size)
        return items[start : start + page_size] or self.items[:page_size]

    def recommend(self, page: int = 1, page_size: int = 10) -> list[core.VideoItem]:
        return self._page(page, page_size)

    def popular(self, page: int = 1, page_size: int = 10) -> list[core.VideoItem]:
        return self._page(page, page_size)

    def precious(self, page: int = 1, page_size: int = 10) -> list[core.VideoItem]:
        return self._page(page, page_size)

    def region_ranking(self, rid: int, day: int = 3, page: int = 1, page_size: int = 10) -> list[core.VideoItem]:
        return self._page(page, page_size)

    def bangumi(
        self,
        category: str = "番剧",
        *,
        index: bool = False,
        area: str | None = None,
        page: int = 1,
        page_size: int = 10,
    ) -> list[core.VideoItem]:
        return self._page(page, page_size)

    def search(self, keyword: str, page: int = 1, page_size: int = 10) -> list[core.VideoItem]:
        return [item for item in self._page(page, page_size) if keyword or item.title]

    def video(self, ref: str) -> core.VideoItem:
        for item in self.items:
            if ref in {item.bvid, str(item.aid), f"av{item.aid}"}:
                return item
        return self.items[0]

    def comments(self, oid: int, page_size: int = 4, bvid: str | None = None) -> list[core.CommentItem]:
        return [
            core.CommentItem(author="热评用户", message="这是一条测试评论", like=42, ctime=1710000000),
            core.CommentItem(author="第二条", message="评论预览正常", like=7, ctime=1710000300),
        ][:page_size]

    def search_default(self) -> str:
        return "默认搜索词"

    def trending_keywords(self, limit: int = 8) -> list[str]:
        return [f"热词{index}" for index in range(1, limit + 1)]


class TextualImportSmokeTests(unittest.TestCase):
    def _assert_static_with_id_uses_name(
        self,
        *,
        source_path: str,
        class_name: str,
        function_name: str,
        static_id: str,
        expected_name: str,
    ) -> None:
        source = Path(source_path).read_text(encoding="utf-8")
        module = ast.parse(source)
        for node in module.body:
            if isinstance(node, ast.ClassDef) and node.name == class_name:
                for item in node.body:
                    if isinstance(item, ast.FunctionDef) and item.name == function_name:
                        for inner in ast.walk(item):
                            if not isinstance(inner, ast.Call):
                                continue
                            if not isinstance(inner.func, ast.Name) or inner.func.id != "Static":
                                continue
                            keyword_map = {
                                keyword.arg: keyword.value
                                for keyword in inner.keywords
                                if keyword.arg is not None
                            }
                            static_id_value = keyword_map.get("id")
                            if not isinstance(static_id_value, ast.Constant) or static_id_value.value != static_id:
                                continue
                            self.assertTrue(inner.args, f"Static(id={static_id!r}) missing first argument")
                            self.assertIsInstance(inner.args[0], ast.Name)
                            self.assertEqual(inner.args[0].id, expected_name)
                            return
        self.fail(f"{class_name}.{function_name} Static(id={static_id!r}) not found")

    def _assert_query_one_update_uses_name(
        self,
        *,
        source_path: str,
        class_name: str,
        function_name: str,
        query_selector: str,
        expected_name: str,
    ) -> None:
        source = Path(source_path).read_text(encoding="utf-8")
        module = ast.parse(source)
        for node in module.body:
            if isinstance(node, ast.ClassDef) and node.name == class_name:
                for item in node.body:
                    if isinstance(item, ast.FunctionDef) and item.name == function_name:
                        for inner in ast.walk(item):
                            if not isinstance(inner, ast.Call):
                                continue
                            if not isinstance(inner.func, ast.Attribute) or inner.func.attr != "update":
                                continue
                            target_call = inner.func.value
                            if not isinstance(target_call, ast.Call):
                                continue
                            if not isinstance(target_call.func, ast.Attribute) or target_call.func.attr != "query_one":
                                continue
                            if not target_call.args:
                                continue
                            selector_arg = target_call.args[0]
                            if not isinstance(selector_arg, ast.Constant) or selector_arg.value != query_selector:
                                continue
                            self.assertTrue(inner.args, f"query_one({query_selector!r}).update missing argument")
                            self.assertIsInstance(inner.args[0], ast.Name)
                            self.assertEqual(inner.args[0].id, expected_name)
                            return
        self.fail(f"{class_name}.{function_name} query_one({query_selector!r}).update(...) not found")

    def test_create_app_exposes_metadata(self) -> None:
        app = textual_app.create_app()
        self.assertEqual(app.TITLE, "BiliTerminal")
        self.assertEqual(app.CSS_PATH, "styles/bili_dark.tcss")
        self.assertTrue(textual_app.KEYMAP_SUMMARY)

    def test_create_app_uses_shared_metadata_constants(self) -> None:
        app = textual_app.create_app()
        self.assertEqual(app.TITLE, textual_app.APP_TITLE)
        self.assertEqual(app.CSS_PATH, textual_app.APP_CSS_PATH)
        self.assertEqual(app.SUB_TITLE, textual_app.APP_SUB_TITLE)
        self.assertEqual(getattr(app, "ENABLE_COMMAND_PALETTE", False), textual_app.APP_ENABLE_COMMAND_PALETTE)

    def test_command_palette_is_enabled(self) -> None:
        app = textual_app.create_app()
        self.assertTrue(getattr(app, "ENABLE_COMMAND_PALETTE", False))

    def test_keymap_groups_are_backed_by_binding_specs(self) -> None:
        binding_keys = {key for key, _ in textual_app.APP_BINDING_SPECS}
        documented_keys = binding_keys | set(textual_app.APP_CHANNEL_SHORTCUT_KEYS)
        for _, _, group_keys in textual_app.KEYMAP_GROUPS:
            self.assertTrue(set(group_keys).issubset(documented_keys))

    def test_help_groups_cover_all_bindings_and_channel_shortcuts(self) -> None:
        binding_keys = {key for key, _ in textual_app.APP_BINDING_SPECS}
        expected_keys = binding_keys | set(textual_app.APP_CHANNEL_SHORTCUT_KEYS)
        covered_keys = {
            key
            for _, _, group_keys in textual_app.KEYMAP_GROUPS
            for key in group_keys
        }
        self.assertEqual(covered_keys, expected_keys)

    def test_binding_keys_and_help_group_ids_are_unique(self) -> None:
        binding_keys = [key for key, _ in textual_app.APP_BINDING_SPECS]
        help_group_ids = [group_id for group_id, _, _, _ in tui_keymap.KEYMAP_HELP_GROUPS]
        self.assertEqual(len(binding_keys), len(set(binding_keys)))
        self.assertEqual(len(help_group_ids), len(set(help_group_ids)))

    def test_channel_shortcut_keys_keep_expected_order_and_help_group_mapping(self) -> None:
        self.assertEqual(tui_keymap.APP_CHANNEL_SHORTCUT_KEYS, tuple("1234567890"))
        channels_jump = {
            group_id: keys
            for group_id, _, _, keys in tui_keymap.KEYMAP_HELP_GROUPS
        }["channels-jump"]
        self.assertEqual(channels_jump, tui_keymap.APP_CHANNEL_SHORTCUT_KEYS)

    def test_summary_and_help_lines_are_derived_from_help_groups(self) -> None:
        expected_summary = [(group_id, legend) for group_id, legend, _, _ in tui_keymap.KEYMAP_HELP_GROUPS]
        expected_help_lines = [f"{legend} {label}" for _, legend, label, _ in tui_keymap.KEYMAP_HELP_GROUPS]
        self.assertEqual(textual_app.KEYMAP_SUMMARY, expected_summary)
        self.assertEqual(tui_keymap.HELP_LINES, expected_help_lines)

    def test_help_lookup_and_theme_source_are_derived_from_help_groups(self) -> None:
        expected_lookup = {
            group_id: (legend, label, keys)
            for group_id, legend, label, keys in tui_keymap.KEYMAP_HELP_GROUPS
        }
        self.assertEqual(tui_keymap.KEYMAP_HELP_BY_ID, expected_lookup)
        self.assertEqual(tui_keymap.THEME_TOGGLE_SOURCE_TEXT, expected_lookup["theme"][0])
        self.assertEqual(tui_keymap.THEME_MENU_SOURCE_TEXT, "主题菜单")

    def test_help_text_uses_shared_keymap_groups(self) -> None:
        expected_lines = [f"{legend} {label}" for _, legend, label, _ in tui_keymap.KEYMAP_HELP_GROUPS]
        self.assertEqual(help_text().splitlines(), expected_lines)
        self.assertEqual(DEFAULT_SEARCH_PLACEHOLDER, tui_keymap.SEARCH_PLACEHOLDER_TEXT)

    def test_default_search_placeholder_is_derived_from_shared_constant(self) -> None:
        source = Path("bili_terminal/tui/utils.py").read_text(encoding="utf-8")
        module = ast.parse(source)
        for node in module.body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "DEFAULT_SEARCH_PLACEHOLDER":
                        self.assertIsInstance(node.value, ast.Name)
                        self.assertEqual(node.value.id, "SEARCH_PLACEHOLDER_TEXT")
                        return
        self.fail("DEFAULT_SEARCH_PLACEHOLDER assignment not found")

    def test_search_status_constants_keep_expected_copy(self) -> None:
        self.assertEqual(DEFAULT_COMMENT_PANEL_TITLE, "评论预览")
        self.assertEqual(DEFAULT_COMMENT_PREVIEW_EMPTY_MESSAGE, "按 c 加载评论预览")
        self.assertEqual(DEFAULT_NO_VISIBLE_VIDEO_MESSAGE, "当前没有可展示的视频")
        self.assertEqual(DEFAULT_NO_RECENT_SEARCH_STATUS, "没有最近搜索记录")
        self.assertEqual(DEFAULT_NO_DEFAULT_SEARCH_STATUS, "当前没有默认搜索词")
        self.assertEqual(DEFAULT_DEFAULT_SEARCH_LOAD_FAILED_PREFIX, "默认搜索词加载失败:")
        self.assertEqual(DEFAULT_EMPTY_RECENT_SEARCHES_TEXT, "暂无")
        self.assertEqual(format_recent_searches_text([]), "最近搜索: 暂无")
        self.assertEqual(format_recent_searches_text(["原神", "星铁"]), "最近搜索: 原神 / 星铁")
        self.assertEqual(format_no_video_status("查看"), "当前没有可查看的视频")
        self.assertEqual(format_no_video_status("播放音频"), "当前没有可播放音频的视频")
        self.assertEqual(format_help_overlay_status(True), "帮助浮层已打开")
        self.assertEqual(format_help_overlay_status(False), "帮助浮层已关闭")
        self.assertEqual(format_search_title("原神", 3), "搜索: 原神 · 第 3 页")
        self.assertEqual(format_status_text("加载完成"), "状态：加载完成")
        self.assertEqual(theme_label("light"), "浅色")
        self.assertEqual(theme_label("LIGHT"), "浅色")
        self.assertEqual(theme_label("dark"), "深色")
        self.assertEqual(theme_label("claude"), "Claude")
        self.assertEqual(format_theme_status_message("light", "Ctrl+T / F2"), "主题已切换为 浅色（Ctrl+T / F2）")
        self.assertEqual(format_theme_status_message("claude", "主题菜单"), "主题已切换为 Claude（主题菜单）")
        self.assertEqual(
            format_theme_status_message("dark", "Ctrl+T / F2", unchanged=True),
            "当前已是深色主题（Ctrl+T / F2）",
        )

    def test_page_hints_use_shared_keymap_groups(self) -> None:
        self.assertEqual(tui_keymap.HOME_SUBTITLE_TEXT, "Tab / Shift+Tab 切换分区 / 1-9 / 0 直选分区")
        self.assertEqual(tui_keymap.HOME_SIDEBAR_INTRO_TEXT, "Tab / Shift+Tab 切换分区\n1-9 / 0 直选分区")
        self.assertEqual(
            tui_keymap.HOME_FEED_HINT_TEXT,
            "↑/↓ / j/k 移动 · Enter 详情 · c 评论 · o 浏览器打开 · Shift+W 稍后看开关 · f 收藏 · a 播放/暂停 · x 停止",
        )
        self.assertEqual(
            tui_keymap.DETAIL_HINT_TEXT,
            "↑/↓ / j/k 移动 · PgUp / PgDn 详情滚动 · a 播放/暂停 · x 停止 · Shift+W 稍后看开关 · f 收藏 · c 评论 · Esc / b 返回",
        )
        self.assertEqual(
            tui_keymap.HISTORY_SUBTITLE_TEXT,
            "最近浏览 · Enter 详情 · o 浏览器打开 · a 播放/暂停 · x 停止",
        )
        self.assertEqual(
            tui_keymap.FAVORITES_SUBTITLE_TEXT,
            "收藏夹 · f 收藏 · Enter 详情 · o 浏览器打开",
        )
        self.assertEqual(
            tui_keymap.WATCH_LATER_SUBTITLE_TEXT,
            "稍后看队列 · Shift+W 稍后看开关 · Enter 详情 · o 浏览器打开",
        )
        self.assertEqual(
            tui_keymap.WATCH_LATER_FEED_HINT_TEXT,
            "↑/↓ / j/k 移动 · Enter 详情 · o 浏览器打开 · Shift+W 稍后看开关",
        )
        self.assertEqual(
            tui_keymap.THEME_PICKER_HINT_TEXT,
            "↑/↓ / j/k 移动 · Enter 详情 · Esc / b 返回",
        )
        self.assertEqual(
            tui_keymap.SEARCH_SUBTITLE_TEXT,
            "支持中文实时输入 · Enter 详情 · l 最近搜索 · d 默认搜索词",
        )
        self.assertEqual(tui_keymap.SEARCH_EMPTY_PROMPT_TEXT, "请输入关键词后按 Enter 开始搜索")

    def test_home_screen_subtitle_references_shared_hint_constant(self) -> None:
        source = Path("bili_terminal/tui/screens/home.py").read_text(encoding="utf-8")
        module = ast.parse(source)
        for node in module.body:
            if isinstance(node, ast.ClassDef) and node.name == "HomeScreen":
                for item in node.body:
                    if isinstance(item, ast.FunctionDef) and item.name == "subtitle_text":
                        return_names = {
                            inner.id
                            for inner in ast.walk(item)
                            if isinstance(inner, ast.Name)
                        }
                        self.assertIn("HOME_SUBTITLE_TEXT", return_names)
                        return
        self.fail("HomeScreen.subtitle_text not found")

    def test_base_feed_compose_references_shared_sidebar_intro_constant(self) -> None:
        self._assert_static_with_id_uses_name(
            source_path="bili_terminal/tui/screens/home.py",
            class_name="BaseFeedScreen",
            function_name="compose",
            static_id="sidebar-intro",
            expected_name="HOME_SIDEBAR_INTRO_TEXT",
        )

    def test_base_feed_compose_references_shared_feed_hint_constant(self) -> None:
        source = Path("bili_terminal/tui/screens/home.py").read_text(encoding="utf-8")
        module = ast.parse(source)
        for node in module.body:
            if isinstance(node, ast.ClassDef) and node.name == "BaseFeedScreen":
                for item in node.body:
                    if isinstance(item, ast.FunctionDef) and item.name == "_refresh_header":
                        attrs = {inner.attr for inner in ast.walk(item) if isinstance(inner, ast.Attribute)}
                        self.assertIn("feed_hint_text", attrs)
                        return
        self.fail("BaseFeedScreen._refresh_header not found")

    def test_detail_screen_compose_references_shared_detail_hint_constant(self) -> None:
        self._assert_static_with_id_uses_name(
            source_path="bili_terminal/tui/screens/detail.py",
            class_name="DetailScreen",
            function_name="compose",
            static_id="detail-hint",
            expected_name="DETAIL_HINT_TEXT",
        )

    def test_history_screen_subtitle_references_shared_hint_constant(self) -> None:
        source = Path("bili_terminal/tui/screens/history.py").read_text(encoding="utf-8")
        module = ast.parse(source)
        for node in module.body:
            if isinstance(node, ast.ClassDef) and node.name == "HistoryScreen":
                for item in node.body:
                    if isinstance(item, ast.FunctionDef) and item.name == "subtitle_text":
                        names = {inner.id for inner in ast.walk(item) if isinstance(inner, ast.Name)}
                        self.assertIn("HISTORY_SUBTITLE_TEXT", names)
                        return
        self.fail("HistoryScreen.subtitle_text not found")

    def test_favorites_screen_subtitle_references_shared_hint_constant(self) -> None:
        source = Path("bili_terminal/tui/screens/favorites.py").read_text(encoding="utf-8")
        module = ast.parse(source)
        for node in module.body:
            if isinstance(node, ast.ClassDef) and node.name == "FavoritesScreen":
                for item in node.body:
                    if isinstance(item, ast.FunctionDef) and item.name == "subtitle_text":
                        names = {inner.id for inner in ast.walk(item) if isinstance(inner, ast.Name)}
                        self.assertIn("FAVORITES_SUBTITLE_TEXT", names)
                        return
        self.fail("FavoritesScreen.subtitle_text not found")

    def test_theme_picker_compose_references_shared_hint_constant(self) -> None:
        self._assert_static_with_id_uses_name(
            source_path="bili_terminal/tui/screens/theme_picker.py",
            class_name="ThemePickerScreen",
            function_name="compose",
            static_id="theme-picker-hint",
            expected_name="THEME_PICKER_HINT_TEXT",
        )

    def test_search_screen_subtitle_references_shared_hint_constant(self) -> None:
        source = Path("bili_terminal/tui/screens/search.py").read_text(encoding="utf-8")
        module = ast.parse(source)
        for node in module.body:
            if isinstance(node, ast.ClassDef) and node.name == "SearchScreen":
                for item in node.body:
                    if isinstance(item, ast.FunctionDef) and item.name == "subtitle_text":
                        names = {inner.id for inner in ast.walk(item) if isinstance(inner, ast.Name)}
                        self.assertIn("SEARCH_SUBTITLE_TEXT", names)
                        return
        self.fail("SearchScreen.subtitle_text not found")

    def test_search_screen_title_references_shared_title_formatter(self) -> None:
        source = Path("bili_terminal/tui/screens/search.py").read_text(encoding="utf-8")
        module = ast.parse(source)
        for node in module.body:
            if isinstance(node, ast.ClassDef) and node.name == "SearchScreen":
                for item in node.body:
                    if isinstance(item, ast.FunctionDef) and item.name == "screen_title":
                        names = {inner.id for inner in ast.walk(item) if isinstance(inner, ast.Name)}
                        self.assertIn("format_search_title", names)
                        return
        self.fail("SearchScreen.screen_title not found")

    def test_search_screen_empty_prompt_references_shared_constant(self) -> None:
        source = Path("bili_terminal/tui/screens/search.py").read_text(encoding="utf-8")
        module = ast.parse(source)
        matched = 0
        for node in module.body:
            if isinstance(node, ast.ClassDef) and node.name == "SearchScreen":
                for item in node.body:
                    if isinstance(item, ast.FunctionDef) and item.name in {"fetch_snapshot", "execute_search"}:
                        names = {inner.id for inner in ast.walk(item) if isinstance(inner, ast.Name)}
                        self.assertIn("SEARCH_EMPTY_PROMPT_TEXT", names)
                        matched += 1
        self.assertEqual(matched, 2)

    def test_textual_adapter_search_uses_shared_title_formatter(self) -> None:
        adapter = TextualAdapter(client=FakeClient(), history_store=core.HistoryStore(path=":memory:"))
        snapshot = adapter.search("测试", page=2, page_size=3)
        self.assertEqual(snapshot.title, "搜索: 测试 · 第 2 页")

    def test_home_and_search_reuse_shared_search_status_constants(self) -> None:
        for source_path, class_name, expected_names in (
            (
                "bili_terminal/tui/screens/home.py",
                "BaseFeedScreen",
                {
                    "DEFAULT_NO_RECENT_SEARCH_STATUS",
                    "DEFAULT_NO_DEFAULT_SEARCH_STATUS",
                    "DEFAULT_DEFAULT_SEARCH_LOAD_FAILED_PREFIX",
                },
            ),
            (
                "bili_terminal/tui/screens/search.py",
                "SearchScreen",
                {
                    "DEFAULT_NO_RECENT_SEARCH_STATUS",
                    "DEFAULT_NO_DEFAULT_SEARCH_STATUS",
                    "DEFAULT_DEFAULT_SEARCH_LOAD_FAILED_PREFIX",
                },
            ),
        ):
            source = Path(source_path).read_text(encoding="utf-8")
            module = ast.parse(source)
            for node in module.body:
                if isinstance(node, ast.ClassDef) and node.name == class_name:
                    names = {inner.id for inner in ast.walk(node) if isinstance(inner, ast.Name)}
                    self.assertTrue(expected_names.issubset(names))
                    break
            else:
                self.fail(f"{class_name} not found in {source_path}")

    def test_home_and_utils_reuse_no_video_status_formatter(self) -> None:
        for source_path, class_name in (
            ("bili_terminal/tui/screens/home.py", "BaseFeedScreen"),
            ("bili_terminal/tui/utils.py", "TextualAdapter"),
        ):
            source = Path(source_path).read_text(encoding="utf-8")
            module = ast.parse(source)
            for node in module.body:
                if isinstance(node, ast.ClassDef) and node.name == class_name:
                    names = {inner.id for inner in ast.walk(node) if isinstance(inner, ast.Name)}
                    self.assertIn("format_no_video_status", names)
                    break
            else:
                self.fail(f"{class_name} not found in {source_path}")

    def test_home_screen_feed_hint_is_overridable(self) -> None:
        source = Path("bili_terminal/tui/screens/home.py").read_text(encoding="utf-8")
        module = ast.parse(source)
        for node in module.body:
            if isinstance(node, ast.ClassDef) and node.name == "BaseFeedScreen":
                method_names = {item.name for item in node.body if isinstance(item, ast.FunctionDef)}
                self.assertIn("feed_hint_text", method_names)
                self.assertIn("show_watch_later", method_names)
                for item in node.body:
                    if isinstance(item, ast.FunctionDef) and item.name == "_refresh_header":
                        attrs = {inner.attr for inner in ast.walk(item) if isinstance(inner, ast.Attribute)}
                        self.assertIn("feed_hint_text", attrs)
                        return
        self.fail("BaseFeedScreen.feed_hint_text not found")

    def test_comment_view_and_screens_reuse_comment_constants(self) -> None:
        checks = (
            ("bili_terminal/tui/widgets/comment_view.py", None, {"DEFAULT_COMMENT_PANEL_TITLE", "DEFAULT_COMMENT_PREVIEW_EMPTY_MESSAGE"}),
            ("bili_terminal/tui/screens/home.py", "BaseFeedScreen", {"DEFAULT_COMMENT_PANEL_TITLE", "DEFAULT_COMMENT_PREVIEW_EMPTY_MESSAGE", "DEFAULT_NO_VISIBLE_VIDEO_MESSAGE"}),
            ("bili_terminal/tui/screens/detail.py", "DetailScreen", {"DEFAULT_COMMENT_PANEL_TITLE"}),
        )
        for source_path, class_name, expected_names in checks:
            source = Path(source_path).read_text(encoding="utf-8")
            module = ast.parse(source)
            target = module
            if class_name is not None:
                for node in module.body:
                    if isinstance(node, ast.ClassDef) and node.name == class_name:
                        target = node
                        break
                else:
                    self.fail(f"{class_name} not found in {source_path}")
            names = {inner.id for inner in ast.walk(target) if isinstance(inner, ast.Name)}
            self.assertTrue(expected_names.issubset(names), f"missing names in {source_path}: {expected_names - names}")

    def test_home_and_search_meta_reuse_recent_searches_formatter(self) -> None:
        for source_path, class_name, function_name in (
            ("bili_terminal/tui/screens/home.py", "BaseFeedScreen", "meta_text"),
            ("bili_terminal/tui/screens/search.py", "SearchScreen", "meta_text"),
        ):
            source = Path(source_path).read_text(encoding="utf-8")
            module = ast.parse(source)
            for node in module.body:
                if isinstance(node, ast.ClassDef) and node.name == class_name:
                    for item in node.body:
                        if isinstance(item, ast.FunctionDef) and item.name == function_name:
                            names = {inner.id for inner in ast.walk(item) if isinstance(inner, ast.Name)}
                            self.assertIn("format_recent_searches_text", names)
                            break
                    else:
                        self.fail(f"{class_name}.{function_name} not found")
                    break
            else:
                self.fail(f"{class_name} not found in {source_path}")

    def test_home_help_overlay_reuses_recent_searches_formatter(self) -> None:
        source = Path("bili_terminal/tui/screens/home.py").read_text(encoding="utf-8")
        module = ast.parse(source)
        for node in module.body:
            if isinstance(node, ast.ClassDef) and node.name == "BaseFeedScreen":
                for item in node.body:
                    if isinstance(item, ast.FunctionDef) and item.name == "_update_help_overlay":
                        names = {inner.id for inner in ast.walk(item) if isinstance(inner, ast.Name)}
                        self.assertIn("format_recent_searches_text", names)
                        return
        self.fail("BaseFeedScreen._update_help_overlay not found")

    def test_home_and_detail_reuse_status_formatter(self) -> None:
        for source_path, class_name in (
            ("bili_terminal/tui/screens/home.py", "BaseFeedScreen"),
            ("bili_terminal/tui/screens/detail.py", "DetailScreen"),
        ):
            source = Path(source_path).read_text(encoding="utf-8")
            module = ast.parse(source)
            for node in module.body:
                if isinstance(node, ast.ClassDef) and node.name == class_name:
                    for item in node.body:
                        if isinstance(item, ast.FunctionDef) and item.name == "set_status":
                            names = {inner.id for inner in ast.walk(item) if isinstance(inner, ast.Name)}
                            self.assertIn("format_status_text", names)
                            break
                    else:
                        self.fail(f"{class_name}.set_status not found")
                    break
            else:
                self.fail(f"{class_name} not found in {source_path}")

    def test_home_and_detail_toggle_help_reuse_help_overlay_status_formatter(self) -> None:
        for source_path, class_name in (
            ("bili_terminal/tui/screens/home.py", "BaseFeedScreen"),
            ("bili_terminal/tui/screens/detail.py", "DetailScreen"),
        ):
            source = Path(source_path).read_text(encoding="utf-8")
            module = ast.parse(source)
            for node in module.body:
                if isinstance(node, ast.ClassDef) and node.name == class_name:
                    for item in node.body:
                        if isinstance(item, ast.FunctionDef) and item.name == "toggle_help":
                            names = {inner.id for inner in ast.walk(item) if isinstance(inner, ast.Name)}
                            self.assertIn("format_help_overlay_status", names)
                            break
                    else:
                        self.fail(f"{class_name}.toggle_help not found")
                    break
            else:
                self.fail(f"{class_name} not found in {source_path}")

    def test_bili_terminal_app_set_theme_default_uses_shared_source_constant(self) -> None:
        source = Path("bili_terminal/tui/app.py").read_text(encoding="utf-8")
        module = ast.parse(source)
        for node in module.body:
            if isinstance(node, ast.If):
                for class_node in node.body:
                    if isinstance(class_node, ast.ClassDef) and class_node.name == "BiliTerminalApp":
                        for item in class_node.body:
                            if isinstance(item, ast.FunctionDef) and item.name == "set_theme":
                                self.assertTrue(item.args.kw_defaults)
                                default = item.args.kw_defaults[0]
                                self.assertIsInstance(default, ast.Name)
                                self.assertEqual(default.id, "THEME_TOGGLE_SOURCE_TEXT")
                                return
        self.fail("BiliTerminalApp.set_theme not found")

    def test_bili_terminal_app_set_theme_references_theme_status_formatter(self) -> None:
        source = Path("bili_terminal/tui/app.py").read_text(encoding="utf-8")
        module = ast.parse(source)
        for node in module.body:
            if isinstance(node, ast.If):
                for class_node in node.body:
                    if isinstance(class_node, ast.ClassDef) and class_node.name == "BiliTerminalApp":
                        for item in class_node.body:
                            if isinstance(item, ast.FunctionDef) and item.name == "set_theme":
                                names = {inner.id for inner in ast.walk(item) if isinstance(inner, ast.Name)}
                                self.assertIn("format_theme_status_message", names)
                                return
        self.fail("BiliTerminalApp.set_theme not found")

    def test_bili_terminal_app_set_theme_reuses_current_screen_status_helper(self) -> None:
        source = Path("bili_terminal/tui/app.py").read_text(encoding="utf-8")
        module = ast.parse(source)
        for node in module.body:
            if isinstance(node, ast.If):
                for class_node in node.body:
                    if isinstance(class_node, ast.ClassDef) and class_node.name == "BiliTerminalApp":
                        method_names = {item.name for item in class_node.body if isinstance(item, ast.FunctionDef)}
                        self.assertIn("_set_current_screen_status", method_names)
                        for item in class_node.body:
                            if isinstance(item, ast.FunctionDef) and item.name == "set_theme":
                                attrs = {inner.attr for inner in ast.walk(item) if isinstance(inner, ast.Attribute)}
                                self.assertIn("_set_current_screen_status", attrs)
                                return
        self.fail("BiliTerminalApp.set_theme not found")

    def test_bili_terminal_app_theme_selection_uses_shared_menu_source_constant(self) -> None:
        source = Path("bili_terminal/tui/app.py").read_text(encoding="utf-8")
        module = ast.parse(source)
        for node in module.body:
            if isinstance(node, ast.If):
                for class_node in node.body:
                    if isinstance(class_node, ast.ClassDef) and class_node.name == "BiliTerminalApp":
                        for item in class_node.body:
                            if isinstance(item, ast.FunctionDef) and item.name == "_handle_theme_selection":
                                names = {inner.id for inner in ast.walk(item) if isinstance(inner, ast.Name)}
                                self.assertIn("THEME_MENU_SOURCE_TEXT", names)
                                return
        self.fail("BiliTerminalApp._handle_theme_selection not found")

    def test_keymap_includes_watch_later_bindings_and_help_groups(self) -> None:
        binding_map = dict(tui_keymap.APP_BINDING_SPECS)
        self.assertEqual(binding_map["w"], "show_watch_later")
        self.assertEqual(binding_map["W"], "toggle_watch_later")
        help_group_ids = {group_id for group_id, _, _, _ in tui_keymap.KEYMAP_HELP_GROUPS}
        self.assertIn("watch-later-view", help_group_ids)
        self.assertIn("watch-later-toggle", help_group_ids)
        self.assertEqual(
            tui_keymap.KEYMAP_HELP_BY_ID["watch-later-view"],
            ("w", "稍后看", ("w",)),
        )
        self.assertEqual(
            tui_keymap.KEYMAP_HELP_BY_ID["watch-later-toggle"],
            ("Shift+W", "稍后看开关", ("W",)),
        )

    def test_watch_later_screen_and_app_routing_are_present(self) -> None:
        source = Path("bili_terminal/tui/app.py").read_text(encoding="utf-8")
        module = ast.parse(source)
        import_names = set()
        found = False
        for node in module.body:
            if isinstance(node, ast.Try):
                for item in node.body:
                    if isinstance(item, ast.ImportFrom):
                        import_names.update(alias.name for alias in item.names)
                for item in node.orelse:
                    if isinstance(item, ast.ImportFrom):
                        import_names.update(alias.name for alias in item.names)
            if isinstance(node, ast.If):
                for item in node.body:
                    if isinstance(item, ast.ClassDef) and item.name == "BiliTerminalApp":
                        method_names = {method.name for method in item.body if isinstance(method, ast.FunctionDef)}
                        self.assertIn("open_watch_later", method_names)
                        self.assertIn("action_show_watch_later", method_names)
                        self.assertIn("action_toggle_watch_later", method_names)
                        found = True
        self.assertIn("WatchLaterScreen", import_names)
        self.assertTrue(found, "BiliTerminalApp watch later routing not found")

    def test_app_registers_textual_keymap(self) -> None:
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
                "w",
                "W",
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
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.client = FakeClient()
        self.history_store = core.HistoryStore(path=f"{self.temp_dir.name}/history.json")
        self.history_store.add_keyword("原神")
        self.history_store.add_video(self.client.items[0])
        self.history_store.add_favorite(self.client.items[1])

    def make_app(self):
        return textual_app.create_app(client=self.client, history_store=self.history_store)

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

    async def test_watch_later_shortcuts_add_open_and_remove(self) -> None:
        app = self.make_app()
        async with app.run_test(size=(120, 36)) as pilot:
            await pilot.press("W")
            await pilot.pause()
            self.assertTrue(self.history_store.is_watch_later(self.client.items[0]))
            self.assertEqual(app.screen.__class__.__name__, "HomeScreen")
            await pilot.press("w")
            await pilot.pause()
            self.assertEqual(app.screen.__class__.__name__, "WatchLaterScreen")
            watch_later_screen = app.screen
            self.assertEqual(getattr(watch_later_screen, "snapshot").videos[0].title, self.client.items[0].title)
            await pilot.press("W")
            await pilot.pause()
            self.assertEqual(self.history_store.get_watch_later_videos(), [])
            self.assertEqual(getattr(app.screen, "snapshot").videos, ())

    async def test_theme_config_hot_reload_switches_screen_class(self) -> None:
        config_path = f"{self.temp_dir.name}/config.toml"
        with open(config_path, "w", encoding="utf-8") as handle:
            handle.write("[ui]\ntheme = \"dark\"\n")
        with mock.patch.dict(os.environ, {"BILITERMINAL_CONFIG": config_path}, clear=False):
            app = self.make_app()
            async with app.run_test(size=(120, 36)) as pilot:
                await pilot.pause()
                self.assertFalse(app.screen.has_class("theme-light"))
                dark_status_background = str(app.screen.query_one("#status-line").styles.background)
                with open(config_path, "w", encoding="utf-8") as handle:
                    handle.write("[ui]\ntheme = \"light\"\n")
                app._poll_config()
                await pilot.pause()
                self.assertTrue(app.screen.has_class("theme-light"))
                light_status_background = str(app.screen.query_one("#status-line").styles.background)
                self.assertNotEqual(dark_status_background, light_status_background)
                with open(config_path, "w", encoding="utf-8") as handle:
                    handle.write("[ui]\ntheme = \"claude\"\n")
                app._poll_config()
                await pilot.pause()
                self.assertFalse(app.screen.has_class("theme-light"))
                self.assertTrue(app.screen.has_class("theme-claude"))
                claude_status_background = str(app.screen.query_one("#status-line").styles.background)
                self.assertNotEqual(light_status_background, claude_status_background)

    async def test_ctrl_t_cycles_themes_and_persists_config(self) -> None:
        config_path = f"{self.temp_dir.name}/config.toml"
        with open(config_path, "w", encoding="utf-8") as handle:
            handle.write("[ui]\ntheme = \"dark\"\n")
        with mock.patch.dict(os.environ, {"BILITERMINAL_CONFIG": config_path}, clear=False):
            app = self.make_app()
            async with app.run_test(size=(120, 36)) as pilot:
                await pilot.pause()
                dark_status_background = str(app.screen.query_one("#status-line").styles.background)
                dark_layout_background = str(app.screen.query_one("#browser-layout").styles.background)
                self.assertFalse(app.screen.has_class("theme-light"))
                await pilot.press("ctrl+t")
                await pilot.pause()
                self.assertTrue(app.screen.has_class("theme-light"))
                await pilot.press("f2")
                await pilot.pause()
                self.assertFalse(app.screen.has_class("theme-light"))
                self.assertTrue(app.screen.has_class("theme-claude"))
                await pilot.press("ctrl+t")
                await pilot.pause()
                self.assertFalse(app.screen.has_class("theme-light"))
                self.assertFalse(app.screen.has_class("theme-claude"))
                await pilot.press("ctrl+t")
                await pilot.pause()
                self.assertTrue(app.screen.has_class("theme-light"))
                light_status_background = str(app.screen.query_one("#status-line").styles.background)
                light_layout_background = str(app.screen.query_one("#browser-layout").styles.background)
                self.assertNotEqual(dark_status_background, light_status_background)
                self.assertNotEqual(dark_layout_background, light_layout_background)
                with open(config_path, "r", encoding="utf-8") as handle:
                    self.assertIn('theme = "light"', handle.read())

    async def test_change_theme_action_opens_custom_theme_picker(self) -> None:
        config_path = f"{self.temp_dir.name}/config.toml"
        with open(config_path, "w", encoding="utf-8") as handle:
            handle.write("[ui]\ntheme = \"dark\"\n")
        with mock.patch.dict(os.environ, {"BILITERMINAL_CONFIG": config_path}, clear=False):
            app = self.make_app()
            async with app.run_test(size=(120, 36)) as pilot:
                await pilot.pause()
                app.action_change_theme()
                await pilot.pause()
                self.assertEqual(app.screen.__class__.__name__, "ThemePickerScreen")
                await pilot.press("down")
                await pilot.press("down")
                await pilot.pause()
                await pilot.press("enter")
                await pilot.pause()
                self.assertEqual(app.screen.__class__.__name__, "HomeScreen")
                self.assertTrue(app.screen.has_class("theme-claude"))
                with open(config_path, "r", encoding="utf-8") as handle:
                    self.assertIn('theme = "claude"', handle.read())

    async def test_theme_picker_supports_jk_navigation(self) -> None:
        config_path = f"{self.temp_dir.name}/config.toml"
        with open(config_path, "w", encoding="utf-8") as handle:
            handle.write("[ui]\ntheme = \"dark\"\n")
        with mock.patch.dict(os.environ, {"BILITERMINAL_CONFIG": config_path}, clear=False):
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
            keys_command = next(command for command in app.get_system_commands(app.screen) if command[0] == "Keys")
            keys_command[2]()
            await pilot.pause()
            self.assertFalse(overlay.has_class("hidden"))
            self.assertFalse(any(type(widget).__name__ == "HelpPanel" for widget in app.screen.walk_children()))
            keys_command = next(command for command in app.get_system_commands(app.screen) if command[0] == "Keys")
            keys_command[2]()
            await pilot.pause()
            self.assertTrue(overlay.has_class("hidden"))

    async def test_command_palette_keys_escape_closes_overlay_without_blank_screen(self) -> None:
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

    async def test_command_palette_uses_active_theme_colors(self) -> None:
        expected = {
            "dark": {
                "app_class": "theme-dark",
                "container_background": "Color(16, 26, 46)",
                "input_box_color": "Color(238, 245, 255)",
                "input_cursor_background": "Color(142, 225, 255)",
                "placeholder_color": "Color(134, 163, 204)",
                "list_background": "Color(16, 26, 46)",
                "option_color": "Color(216, 232, 255)",
                "disabled_color": "Color(134, 163, 204)",
                "loading_color": "Color(142, 225, 255)",
            },
            "light": {
                "app_class": "theme-light",
                "container_background": "Color(255, 255, 255)",
                "input_box_color": "Color(122, 33, 70)",
                "input_cursor_background": "Color(251, 114, 153)",
                "placeholder_color": "Color(177, 114, 141)",
                "list_background": "Color(255, 243, 248)",
                "option_color": "Color(111, 49, 80)",
                "disabled_color": "Color(177, 114, 141)",
                "loading_color": "Color(251, 114, 153)",
            },
            "claude": {
                "app_class": "theme-claude",
                "container_background": "Color(245, 242, 234)",
                "input_box_color": "Color(44, 42, 38)",
                "input_cursor_background": "Color(201, 100, 66)",
                "placeholder_color": "Color(168, 163, 154)",
                "list_background": "Color(245, 242, 234)",
                "option_color": "Color(61, 58, 53)",
                "disabled_color": "Color(168, 163, 154)",
                "loading_color": "Color(201, 100, 66)",
            },
        }
        for theme, theme_expected in expected.items():
            with self.subTest(theme=theme):
                config_path = f"{self.temp_dir.name}/{theme}-config.toml"
                with open(config_path, "w", encoding="utf-8") as handle:
                    handle.write(f"[ui]\ntheme = \"{theme}\"\n")
                with mock.patch.dict(os.environ, {"BILITERMINAL_CONFIG": config_path}, clear=False):
                    app = self.make_app()
                    async with app.run_test(size=(120, 36)) as pilot:
                        await pilot.pause()
                        await pilot.press("ctrl+p")
                        await pilot.pause()
                        await pilot.press("x", "x", "x")
                        await pilot.pause()

                        self.assertEqual(app.screen.__class__.__name__, "CommandPalette")
                        self.assertTrue(app.has_class(theme_expected["app_class"]))
                        container = app.screen.query_one("#--container")
                        input_box = app.screen.query_one("#--input")
                        command_list = app.screen.query_one("CommandList")
                        command_input = app.screen.query_one("CommandInput")
                        loading = app.screen.query_one("LoadingIndicator")
                        self.assertEqual(str(container.styles.background), theme_expected["container_background"])
                        self.assertEqual(str(input_box.styles.color), theme_expected["input_box_color"])
                        self.assertEqual(
                            str(command_input.get_component_styles("input--cursor").background),
                            theme_expected["input_cursor_background"],
                        )
                        self.assertEqual(
                            str(command_input.get_component_styles("input--placeholder").color),
                            theme_expected["placeholder_color"],
                        )
                        self.assertEqual(str(command_list.styles.background), theme_expected["list_background"])
                        self.assertEqual(
                            str(command_list.get_component_styles("option-list--option").color),
                            theme_expected["option_color"],
                        )
                        self.assertEqual(
                            str(
                                command_list.get_component_styles(
                                    "option-list--option",
                                    "option-list--option-disabled",
                                ).color
                            ),
                            theme_expected["disabled_color"],
                        )
                        self.assertEqual(str(loading.styles.color), theme_expected["loading_color"])
                        self.assertFalse(any(type(widget).__name__ == "HelpPanel" for widget in app.screen.walk_children()))

    async def test_theme_toggle_propagates_between_detail_and_home(self) -> None:
        config_path = f"{self.temp_dir.name}/config.toml"
        with open(config_path, "w", encoding="utf-8") as handle:
            handle.write("[ui]\ntheme = \"dark\"\n")
        with mock.patch.dict(os.environ, {"BILITERMINAL_CONFIG": config_path}, clear=False):
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
                self.assertEqual(str(app.screen.query_one("#detail-scroll").styles.background), "Color(255, 243, 248)")
                await pilot.press("b")
                await pilot.pause()
                self.assertEqual(app.screen.__class__.__name__, "HomeScreen")
                self.assertTrue(app.screen.has_class("theme-light"))
                self.assertEqual(str(app.screen.query_one("#channel-list").styles.background), "Color(255, 243, 248)")
