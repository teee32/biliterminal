import io
import json
import tempfile
import unittest
from unittest import mock

from bili_terminal import bilibili_cli as cli


class ParseVideoRefTests(unittest.TestCase):
    def test_parse_bvid_from_plain_text(self) -> None:
        self.assertEqual(cli.parse_video_ref("BV1xx411c7mu"), ("bvid", "BV1xx411c7mu"))

    def test_parse_bvid_from_url(self) -> None:
        self.assertEqual(
            cli.parse_video_ref("https://www.bilibili.com/video/BV1xx411c7mu?p=1"),
            ("bvid", "BV1xx411c7mu"),
        )

    def test_parse_aid_from_plain_text(self) -> None:
        self.assertEqual(cli.parse_video_ref("av106"), ("aid", "106"))

    def test_parse_invalid_ref_raises(self) -> None:
        with self.assertRaises(ValueError):
            cli.parse_video_ref("hello")


class FormattingTests(unittest.TestCase):
    def test_normalize_keyword_repairs_utf8_latin1_mojibake(self) -> None:
        self.assertEqual(cli.normalize_keyword("ä¸­æ"), "中文")

    def test_normalize_keyword_drops_suspicious_garbage(self) -> None:
        self.assertEqual(cli.normalize_keyword("ã, æ"), "")

    def test_comments_from_payload_extracts_author_and_message(self) -> None:
        comments = cli.comments_from_payload(
            [
                {
                    "member": {"uname": "测试用户"},
                    "content": {"message": "第一条评论"},
                    "like": 12,
                    "ctime": 1710000000,
                }
            ]
        )
        self.assertEqual(comments[0].author, "测试用户")
        self.assertEqual(comments[0].message, "第一条评论")

    def test_display_width_counts_chinese_as_double_width(self) -> None:
        self.assertEqual(cli.display_width("abc"), 3)
        self.assertEqual(cli.display_width("中文A"), 5)

    def test_truncate_display_respects_terminal_cell_width(self) -> None:
        self.assertEqual(cli.truncate_display("原神启动测试", 8), "原神...")

    def test_wrap_display_keeps_lines_within_width(self) -> None:
        lines = cli.wrap_display("哔哩哔哩终端首页", 8)
        self.assertTrue(all(cli.display_width(line) <= 8 for line in lines))

    def test_normalize_duration_pads_search_style_value(self) -> None:
        self.assertEqual(cli.normalize_duration("5:5"), "5:05")

    def test_item_from_payload_strips_search_highlight_markup(self) -> None:
        item = cli.item_from_payload(
            {
                "title": '【<em class="keyword">原神</em>】新角色',
                "author": "测试UP",
                "bvid": "BV1xx411c7mu",
                "play": 12345,
                "video_review": 67,
                "like": 89,
                "favorites": 12,
                "duration": "3:21",
                "pubdate": 1710000000,
                "description": "  多余   空格  ",
            }
        )
        self.assertEqual(item.title, "【原神】新角色")
        self.assertEqual(item.description, "多余 空格")

    def test_build_video_url_prefers_redirect(self) -> None:
        self.assertEqual(
            cli.build_video_url({"redirect_url": "https://www.bilibili.com/bangumi/play/ep1", "bvid": "BV1xx411c7mu"}),
            "https://www.bilibili.com/bangumi/play/ep1",
        )

    def test_build_watch_url_supports_bvid(self) -> None:
        self.assertEqual(
            cli.build_watch_url("bvid", "BV1xx411c7mu"),
            "https://www.bilibili.com/video/BV1xx411c7mu",
        )

    def test_build_detail_lines_contains_core_metadata(self) -> None:
        lines = cli.build_detail_lines(
            cli.VideoItem(
                title="标题",
                author="UP",
                bvid="BV1xx411c7mu",
                aid=106,
                duration="1:00",
                play=12345,
                danmaku=6,
                like=7,
                favorite=8,
                pubdate=1710000000,
                description="简介",
                url="https://www.bilibili.com/video/BV1xx411c7mu",
                raw={},
            ),
            width=40,
        )
        self.assertIn("UP主: UP", lines)
        self.assertIn("简介:", lines)

    def test_item_to_history_payload_drops_large_raw_fields(self) -> None:
        payload = cli.item_to_history_payload(
            cli.VideoItem(
                title="标题",
                author="UP",
                bvid="BV1xx411c7mu",
                aid=106,
                duration="1:00",
                play=123,
                danmaku=4,
                like=5,
                favorite=6,
                pubdate=1710000000,
                description="简介",
                url="https://www.bilibili.com/video/BV1xx411c7mu",
                raw={"owner": {"name": "UP"}, "stat": {"view": 123}},
            )
        )
        self.assertNotIn("owner", payload)
        self.assertNotIn("stat", payload)
        self.assertEqual(payload["title"], "标题")


class ClientTests(unittest.TestCase):
    def make_response(self, payload: dict) -> mock.MagicMock:
        response = mock.MagicMock()
        response.read.return_value = json.dumps(payload).encode("utf-8")
        response.headers = {}
        response.__enter__.return_value = response
        response.__exit__.return_value = False
        return response

    def make_text_response(self, payload: str) -> mock.MagicMock:
        response = mock.MagicMock()
        response.read.return_value = payload.encode("utf-8")
        response.headers = {}
        response.__enter__.return_value = response
        response.__exit__.return_value = False
        return response

    @mock.patch.object(cli.BilibiliClient, "_open")
    def test_search_filters_non_video_results(self, mock_open: mock.MagicMock) -> None:
        mock_open.return_value = self.make_response(
            {
                "code": 0,
                "data": {
                    "result": [
                        {"type": "video", "title": "视频A", "author": "UP1", "bvid": "BV1xx411c7mu"},
                        {"type": "ketang", "title": "课程B"},
                    ]
                },
            }
        )
        items = cli.BilibiliClient().search("测试")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].title, "视频A")

    @mock.patch.object(cli.BilibiliClient, "_open")
    def test_api_error_raises(self, mock_open: mock.MagicMock) -> None:
        mock_open.return_value = self.make_response({"code": -352, "message": "-352"})
        with self.assertRaises(cli.BilibiliAPIError):
            cli.BilibiliClient().popular()

    @mock.patch.object(cli.BilibiliClient, "_warmup")
    @mock.patch.object(cli.BilibiliClient, "_open")
    def test_retries_after_http_412(self, mock_open: mock.MagicMock, mock_warmup: mock.MagicMock) -> None:
        error = cli.urllib.error.HTTPError("https://example.com", 412, "Precondition Failed", {}, io.BytesIO(b""))
        self.addCleanup(error.close)
        mock_open.side_effect = [
            error,
            self.make_response({"code": 0, "data": {"list": []}}),
        ]
        items = cli.BilibiliClient().popular()
        self.assertEqual(items, [])
        mock_warmup.assert_called_once()

    @mock.patch.object(cli.BilibiliClient, "_open")
    def test_warmup_hits_homepage_before_referer(self, mock_open: mock.MagicMock) -> None:
        mock_open.return_value = self.make_response({"code": 0})
        cli.BilibiliClient()._warmup("https://www.bilibili.com/video/BV1xx411c7mu")
        urls = [call.args[0].full_url for call in mock_open.call_args_list]
        self.assertEqual(urls, ["https://www.bilibili.com/", "https://www.bilibili.com/video/BV1xx411c7mu"])

    @mock.patch.object(cli.BilibiliClient, "_open")
    def test_recommend_parses_home_feed_items(self, mock_open: mock.MagicMock) -> None:
        mock_open.return_value = self.make_response(
            {
                "code": 0,
                "data": {
                    "item": [
                        {
                            "goto": "av",
                            "title": "首页推荐",
                            "owner": {"name": "UP1"},
                            "bvid": "BV1xx411c7mu",
                            "duration": 99,
                            "stat": {"view": 10, "danmaku": 2, "like": 3, "favorite": 4},
                        }
                    ]
                },
            }
        )
        items = cli.BilibiliClient().recommend()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].title, "首页推荐")

    @mock.patch.object(cli.BilibiliClient, "_open")
    def test_trending_keywords_extracts_display_words(self, mock_open: mock.MagicMock) -> None:
        mock_open.return_value = self.make_response(
            {
                "code": 0,
                "data": {
                    "trending": {
                        "list": [
                            {"show_name": "原神"},
                            {"keyword": "中文"},
                        ]
                    }
                },
            }
        )
        self.assertEqual(cli.BilibiliClient().trending_keywords(2), ["原神", "中文"])

    @mock.patch.object(cli.BilibiliClient, "_open")
    def test_comments_extracts_reply_items(self, mock_open: mock.MagicMock) -> None:
        mock_open.return_value = self.make_response(
            {
                "code": 0,
                "data": {
                    "replies": [
                        {
                            "member": {"uname": "评论者"},
                            "content": {"message": "评论内容"},
                            "like": 9,
                            "ctime": 1710000000,
                        }
                    ]
                },
            }
        )
        comments = cli.BilibiliClient().comments(123)
        self.assertEqual(comments[0].author, "评论者")
        self.assertEqual(comments[0].message, "评论内容")

    @mock.patch.object(cli.BilibiliClient, "_open")
    def test_comments_prefers_bvid_referer_when_present(self, mock_open: mock.MagicMock) -> None:
        mock_open.side_effect = [
            self.make_text_response(
                (
                    '<script>window.__INITIAL_STATE__={"abtest":{"comment_version_hash":"hash123"},'
                    '"defaultWbiKey":{"wbiImgKey":"img","wbiSubKey":"sub"}};(function(){})</script>'
                )
            ),
            self.make_text_response('encWbiKeys:{wbiImgKey:"img2",wbiSubKey:"sub2"}'),
            self.make_response({"code": 0, "data": {"replies": []}}),
        ]
        cli.BilibiliClient().comments(123, bvid="BV1xx411c7mu")
        request = mock_open.call_args_list[-1].args[0]
        self.assertIn("BV1xx411c7mu", request.headers["Referer"])

    @mock.patch.object(cli.BilibiliClient, "_open")
    def test_comments_with_bvid_uses_wbi_main_and_merges_top_replies(self, mock_open: mock.MagicMock) -> None:
        mock_open.side_effect = [
            self.make_text_response(
                (
                    '<script>window.__INITIAL_STATE__={"abtest":{"comment_version_hash":"hash123"},'
                    '"defaultWbiKey":{"wbiImgKey":"img","wbiSubKey":"sub"}};(function(){})</script>'
                )
            ),
            self.make_text_response('encWbiKeys:{wbiImgKey:"img2",wbiSubKey:"sub2"}'),
            self.make_response(
                {
                    "code": 0,
                    "data": {
                        "top_replies": [
                            {
                                "rpid": 1,
                                "member": {"uname": "置顶"},
                                "content": {"message": "置顶评论"},
                                "like": 8,
                                "ctime": 1710000000,
                            }
                        ],
                        "replies": [
                            {
                                "rpid": 2,
                                "member": {"uname": "普通"},
                                "content": {"message": "普通评论"},
                                "like": 3,
                                "ctime": 1710000001,
                            }
                        ],
                    },
                }
            ),
        ]
        comments = cli.BilibiliClient().comments(123, page_size=2, bvid="BV1xx411c7mu")
        request = mock_open.call_args_list[-1].args[0]
        self.assertIn("/x/v2/reply/wbi/main?", request.full_url)
        self.assertIn("web_location=1315875", request.full_url)
        self.assertEqual([comment.author for comment in comments], ["置顶", "普通"])

    @mock.patch.object(cli.BilibiliClient, "_open")
    def test_comments_with_bvid_refreshes_cached_wbi_keys_after_permission_error(self, mock_open: mock.MagicMock) -> None:
        mock_open.side_effect = [
            self.make_text_response(
                (
                    '<script>window.__INITIAL_STATE__={"abtest":{"comment_version_hash":"hash123"},'
                    '"defaultWbiKey":{"wbiImgKey":"img","wbiSubKey":"sub"}};(function(){})</script>'
                )
            ),
            self.make_text_response('encWbiKeys:{wbiImgKey:"oldimg",wbiSubKey:"oldsub"}'),
            self.make_response({"code": -403, "message": "访问权限不足"}),
            self.make_text_response(
                (
                    '<script>window.__INITIAL_STATE__={"abtest":{"comment_version_hash":"hash456"},'
                    '"defaultWbiKey":{"wbiImgKey":"img","wbiSubKey":"sub"}};(function(){})</script>'
                )
            ),
            self.make_text_response('encWbiKeys:{wbiImgKey:"newimg",wbiSubKey:"newsub"}'),
            self.make_response(
                {
                    "code": 0,
                    "data": {
                        "replies": [
                            {
                                "rpid": 2,
                                "member": {"uname": "普通"},
                                "content": {"message": "普通评论"},
                                "like": 3,
                                "ctime": 1710000001,
                            }
                        ]
                    },
                }
            ),
        ]
        comments = cli.BilibiliClient().comments(123, page_size=1, bvid="BV1xx411c7mu")
        request_urls = [call.args[0].full_url for call in mock_open.call_args_list]
        self.assertEqual(request_urls.count("https://www.bilibili.com/video/BV1xx411c7mu"), 2)
        self.assertEqual(comments[0].author, "普通")


class ShellTests(unittest.TestCase):
    def make_store(self) -> cli.HistoryStore:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        return cli.HistoryStore(path=f"{temp_dir.name}/history.json")

    def test_parser_supports_history_command(self) -> None:
        args = cli.build_parser().parse_args(["history"])
        self.assertEqual(args.command, "history")

    def test_parser_supports_tui_command(self) -> None:
        args = cli.build_parser().parse_args(["tui"])
        self.assertEqual(args.command, "tui")

    def test_parser_supports_recommend_command(self) -> None:
        args = cli.build_parser().parse_args(["recommend"])
        self.assertEqual(args.command, "recommend")

    def test_parser_supports_comments_command(self) -> None:
        args = cli.build_parser().parse_args(["comments", "BV1xx411c7mu"])
        self.assertEqual(args.command, "comments")

    def test_resolve_target_by_index(self) -> None:
        shell = cli.BilibiliCLI(cli.BilibiliClient(), self.make_store())
        shell.last_items = [
            cli.VideoItem(
                title="标题",
                author="UP",
                bvid="BV1xx411c7mu",
                aid=106,
                duration="1:00",
                play=1,
                danmaku=2,
                like=3,
                favorite=4,
                pubdate=1710000000,
                description="",
                url="https://www.bilibili.com/video/BV1xx411c7mu",
                raw={},
            )
        ]
        self.assertEqual(shell._resolve_target("1"), "BV1xx411c7mu")

    @mock.patch("webbrowser.open")
    def test_open_by_index_uses_last_results(self, mock_open: mock.MagicMock) -> None:
        shell = cli.BilibiliCLI(cli.BilibiliClient(), self.make_store())
        shell.last_items = [
            cli.VideoItem(
                title="标题",
                author="UP",
                bvid="BV1xx411c7mu",
                aid=106,
                duration="1:00",
                play=1,
                danmaku=2,
                like=3,
                favorite=4,
                pubdate=1710000000,
                description="",
                url="https://www.bilibili.com/video/BV1xx411c7mu",
                raw={},
            )
        ]
        with mock.patch("sys.stdout", new=io.StringIO()):
            shell.do_open("1")
        mock_open.assert_called_once_with("https://www.bilibili.com/video/BV1xx411c7mu")

    @mock.patch("webbrowser.open")
    def test_open_video_target_uses_browser(self, mock_open: mock.MagicMock) -> None:
        url = cli.open_video_target("BV1xx411c7mu")
        self.assertEqual(url, "https://www.bilibili.com/video/BV1xx411c7mu")
        mock_open.assert_called_once_with("https://www.bilibili.com/video/BV1xx411c7mu")


class HistoryStoreTests(unittest.TestCase):
    def make_item(self, title: str = "标题", bvid: str = "BV1xx411c7mu") -> cli.VideoItem:
        return cli.VideoItem(
            title=title,
            author="UP",
            bvid=bvid,
            aid=106,
            duration="1:00",
            play=1,
            danmaku=2,
            like=3,
            favorite=4,
            pubdate=1710000000,
            description="简介",
            url=f"https://www.bilibili.com/video/{bvid}",
            raw={},
        )

    def test_history_store_persists_keywords_and_videos(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = f"{temp_dir}/history.json"
            store = cli.HistoryStore(path=path)
            store.add_keyword("原神")
            store.add_video(self.make_item())

            reloaded = cli.HistoryStore(path=path)
            self.assertEqual(reloaded.get_recent_keywords(1), ["原神"])
            self.assertEqual(reloaded.get_recent_videos(1)[0].bvid, "BV1xx411c7mu")

    def test_history_store_deduplicates_keywords(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = cli.HistoryStore(path=f"{temp_dir}/history.json")
            store.add_keyword("原神")
            store.add_keyword("原神")
            self.assertEqual(store.get_recent_keywords(5), ["原神"])

    def test_history_store_repairs_mojibake_keywords_on_load(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = f"{temp_dir}/history.json"
            with open(path, "w", encoding="utf-8") as handle:
                json.dump({"recent_keywords": ["ä¸­æ", "ã, æ", "原神"], "recent_videos": []}, handle, ensure_ascii=False)
            store = cli.HistoryStore(path=path)
            self.assertEqual(store.get_recent_keywords(5), ["中文", "原神"])


class TUIStateTests(unittest.TestCase):
    def make_item(self, title: str = "标题", bvid: str = "BV1xx411c7mu") -> cli.VideoItem:
        return cli.VideoItem(
            title=title,
            author="UP",
            bvid=bvid,
            aid=106,
            duration="1:00",
            play=1,
            danmaku=2,
            like=3,
            favorite=4,
            pubdate=1710000000,
            description="简介",
            url=f"https://www.bilibili.com/video/{bvid}",
            raw={},
        )

    def test_load_items_uses_history_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = cli.HistoryStore(path=f"{temp_dir}/history.json")
            store.add_video(self.make_item())
            tui = cli.BilibiliTUI(cli.BilibiliClient(), store)
            tui.mode = "history"
            tui.load_items()
            self.assertEqual(len(tui.items), 1)
            self.assertEqual(tui.items[0].bvid, "BV1xx411c7mu")

    def test_load_items_uses_home_recommend_channel(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = cli.HistoryStore(path=f"{temp_dir}/history.json")
            client = cli.BilibiliClient()
            client.recommend = mock.MagicMock(return_value=[self.make_item("推荐")])
            client.search_default = mock.MagicMock(return_value="默认词")
            client.trending_keywords = mock.MagicMock(return_value=["热搜"])
            tui = cli.BilibiliTUI(client, store)
            tui.load_items()
            client.recommend.assert_called_once_with(page=1, page_size=tui.limit)
            self.assertEqual(tui.items[0].title, "推荐")

    def test_set_channel_switches_to_target_channel(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = cli.HistoryStore(path=f"{temp_dir}/history.json")
            tui = cli.BilibiliTUI(cli.BilibiliClient(), store)
            tui.load_items = mock.MagicMock()
            tui.set_channel(3, push_current=False)
            self.assertEqual(tui.channel_index, 3)
            tui.load_items.assert_called_once()

    def test_restore_previous_state_returns_to_search(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = cli.HistoryStore(path=f"{temp_dir}/history.json")
            tui = cli.BilibiliTUI(cli.BilibiliClient(), store)
            tui.load_items = mock.MagicMock()
            tui.mode = "search"
            tui.keyword = "原神"
            tui.page = 2
            tui.selected_index = 3
            tui.push_list_state()

            tui.mode = "history"
            tui.keyword = ""
            tui.page = 1
            tui.selected_index = 0
            tui.restore_previous_state()

            self.assertEqual(tui.mode, "search")
            self.assertEqual(tui.keyword, "原神")
            self.assertEqual(tui.page, 2)
            tui.load_items.assert_called_once()

    def test_rerun_last_search_switches_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = cli.HistoryStore(path=f"{temp_dir}/history.json")
            store.add_keyword("鬼畜")
            tui = cli.BilibiliTUI(cli.BilibiliClient(), store)
            tui.switch_mode = mock.MagicMock()
            tui.rerun_last_search()
            tui.switch_mode.assert_called_once_with("search", page=1, keyword="鬼畜")

    def test_refresh_current_view_forces_home_meta_and_comments(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = cli.HistoryStore(path=f"{temp_dir}/history.json")
            tui = cli.BilibiliTUI(cli.BilibiliClient(), store)
            tui.refresh_home_meta = mock.MagicMock()
            tui.load_items = mock.MagicMock()
            tui.refresh_current_view()
            tui.refresh_home_meta.assert_called_once_with(force=True)
            tui.load_items.assert_called_once_with(force_comments=True)
            self.assertIn("已刷新", tui.status)

    def test_refresh_comments_forces_reload_and_updates_status(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = cli.HistoryStore(path=f"{temp_dir}/history.json")
            tui = cli.BilibiliTUI(cli.BilibiliClient(), store)
            tui.items = [self.make_item()]
            tui.ensure_comments_for_selected = mock.MagicMock()
            tui.current_comments = mock.MagicMock(return_value=[cli.CommentItem(author="评论者", message="内容", like=1, ctime=1710000000)])
            tui.refresh_comments()
            tui.ensure_comments_for_selected.assert_called_once_with(force=True)
            self.assertEqual(tui.status, "已加载评论 1 条")

    def test_refresh_comments_surfaces_error_message(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = cli.HistoryStore(path=f"{temp_dir}/history.json")
            tui = cli.BilibiliTUI(cli.BilibiliClient(), store)
            tui.items = [self.make_item()]
            tui.ensure_comments_for_selected = mock.MagicMock()
            tui.current_comment_error = mock.MagicMock(return_value="评论接口受限，请按 o 在浏览器中查看")
            tui.refresh_comments()
            tui.ensure_comments_for_selected.assert_called_once_with(force=True)
            self.assertIn("评论加载失败", tui.status)

    def test_draw_split_view_renders_comments_panel_when_height_allows(self) -> None:
        import curses

        class FakeScreen:
            def addnstr(self, *args, **kwargs) -> None:
                return None

            def hline(self, *args, **kwargs) -> None:
                return None

        with tempfile.TemporaryDirectory() as temp_dir:
            store = cli.HistoryStore(path=f"{temp_dir}/history.json")
            tui = cli.BilibiliTUI(cli.BilibiliClient(), store)
            tui.items = [
                self.make_item("精选"),
                self.make_item("次卡1", "BV1aa411c7mu"),
                self.make_item("次卡2", "BV1bb411c7mu"),
                self.make_item("次卡3", "BV1cc411c7mu"),
            ]
            tui.draw_banner = mock.MagicMock(return_value=6)
            tui.draw_category_row = mock.MagicMock(return_value=1)
            tui.draw_featured_card = mock.MagicMock()
            tui.draw_grid_card = mock.MagicMock()
            tui.draw_comments_panel = mock.MagicMock()
            with mock.patch.object(curses, "ACS_HLINE", "-", create=True):
                tui.draw_split_view(FakeScreen(), 34, 140)
            tui.draw_comments_panel.assert_called_once()

    def test_draw_comments_panel_renders_error_hint(self) -> None:
        class FakeWindow:
            def __init__(self) -> None:
                self.lines: list[str] = []

            def derwin(self, *args, **kwargs) -> "FakeWindow":
                return self

            def box(self) -> None:
                return None

            def addnstr(self, _y: int, _x: int, text: str, *_args) -> None:
                self.lines.append(text)

        with tempfile.TemporaryDirectory() as temp_dir:
            store = cli.HistoryStore(path=f"{temp_dir}/history.json")
            tui = cli.BilibiliTUI(cli.BilibiliClient(), store)
            item = self.make_item()
            tui.items = [item]
            tui.comment_errors[item.bvid or str(item.aid)] = "评论接口受限，请按 o 在浏览器中查看"
            fake = FakeWindow()
            tui.draw_comments_panel(fake, 0, 0, 8, 42)
            rendered = " ".join(fake.lines)
            self.assertIn("评论加载失败", rendered)
            self.assertIn("浏览器", rendered)

    def test_draw_comments_panel_renders_empty_loaded_state(self) -> None:
        class FakeWindow:
            def __init__(self) -> None:
                self.lines: list[str] = []

            def derwin(self, *args, **kwargs) -> "FakeWindow":
                return self

            def box(self) -> None:
                return None

            def addnstr(self, _y: int, _x: int, text: str, *_args) -> None:
                self.lines.append(text)

        with tempfile.TemporaryDirectory() as temp_dir:
            store = cli.HistoryStore(path=f"{temp_dir}/history.json")
            tui = cli.BilibiliTUI(cli.BilibiliClient(), store)
            item = self.make_item()
            key = item.bvid or str(item.aid)
            tui.items = [item]
            tui.comment_cache[key] = []
            tui.comment_loaded.add(key)
            fake = FakeWindow()
            tui.draw_comments_panel(fake, 0, 0, 8, 42)
            rendered = " ".join(fake.lines)
            self.assertIn("暂无可显示热评", rendered)


if __name__ == "__main__":
    unittest.main()
