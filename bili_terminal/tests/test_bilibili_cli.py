import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

from bili_terminal import audio
from bili_terminal import bilibili_cli as cli
from bili_terminal import tui as tui_module
from bili_terminal import video_player as vp


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

    def test_box_drawing_chars_count_as_single_width(self) -> None:
        # 框线字符在部分终端被标为歧义宽度，必须固定按单宽计算，
        # 否则框线与内容会错位（Ghostty 等终端会把歧义字符按双宽渲染）
        for char in "─│╭╮╰╯┄":
            self.assertEqual(cli.char_width(char), 1, f"{char!r} 应按单宽计算")

    def test_card_meta_symbols_are_unambiguous_width(self) -> None:
        # 卡片/详情里与文字混排的符号必须是明确单宽（EAW≠A），
        # 否则在把歧义字符当双宽的终端里会撑破右边框
        import unicodedata

        for char in "▸⋅✦◷❝❤≋≣⇕‹›":
            self.assertNotEqual(
                unicodedata.east_asian_width(char),
                "A",
                f"{char!r} 是歧义宽度，会在某些终端错位",
            )

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
        self.assertIn("👤 UP主: UP", lines)
        self.assertIn("📝 简介:", lines)

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

    def test_extract_audio_stream_prefers_highest_bandwidth_dash_audio(self) -> None:
        stream = cli.extract_audio_stream(
            {
                "data": {
                    "dash": {
                        "audio": [
                            {"id": 30216, "bandwidth": 64000, "baseUrl": "https://example.com/low.m4s"},
                            {"id": 30280, "bandwidth": 192000, "baseUrl": "https://example.com/high.m4s"},
                        ]
                    }
                }
            },
            referer="https://www.bilibili.com/video/BV1xx411c7mu",
            user_agent="UA",
            title="标题",
        )
        self.assertEqual(stream.url, "https://example.com/high.m4s")
        self.assertEqual(stream.source_kind, "dash-audio")

    def test_extract_audio_stream_falls_back_to_durl(self) -> None:
        stream = cli.extract_audio_stream(
            {
                "data": {
                    "durl": [
                        {"url": "https://example.com/fallback.mp4"},
                    ]
                }
            },
            referer="https://www.bilibili.com/video/BV1xx411c7mu",
            user_agent="UA",
            title="标题",
        )
        self.assertEqual(stream.url, "https://example.com/fallback.mp4")
        self.assertEqual(stream.source_kind, "media")

    @mock.patch.object(audio, "pid_exists", return_value=True)
    def test_save_and_load_audio_playback_state(self, _mock_exists: mock.MagicMock) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with mock.patch.dict(os.environ, {"BILITERMINAL_STATE_DIR": temp_dir}, clear=False):
                cli.save_audio_playback_state(
                    cli.AudioPlaybackState(
                        pid=1234,
                        title="标题",
                        video_key="BV1xx411c7mu",
                        paused=True,
                        control_pid=5678,
                        ipc_socket="/tmp/mpv-1234.sock",
                    )
                )
                state = cli.load_audio_playback_state()
        self.assertIsNotNone(state)
        assert state is not None
        self.assertEqual(state.pid, 1234)
        self.assertEqual(state.video_key, "BV1xx411c7mu")
        self.assertEqual(state.backend, "process")
        self.assertTrue(state.paused)
        self.assertEqual(state.control_pid, 5678)
        self.assertEqual(state.ipc_socket, "/tmp/mpv-1234.sock")

    @mock.patch.object(audio, "pid_exists", return_value=True)
    def test_save_and_load_audio_playback_state_with_media_path(self, _mock_exists: mock.MagicMock) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            media_path = os.path.join(temp_dir, "audio.m4a")
            with open(media_path, "wb") as handle:
                handle.write(b"demo")
            with mock.patch.dict(os.environ, {"BILITERMINAL_STATE_DIR": temp_dir}, clear=False):
                cli.save_audio_playback_state(
                    cli.AudioPlaybackState(
                        pid=2345,
                        title="标题",
                        video_key="BV1xx411c7mu",
                        backend="macos-native",
                        paused=False,
                        control_pid=6789,
                        media_path=media_path,
                    )
                )
                state = cli.load_audio_playback_state()
        self.assertIsNotNone(state)
        assert state is not None
        self.assertEqual(state.pid, 2345)
        self.assertEqual(state.backend, "macos-native")
        self.assertEqual(state.control_pid, 6789)
        self.assertEqual(state.media_path, media_path)

    @mock.patch.object(audio, "clear_audio_playback_state")
    @mock.patch.object(audio, "cleanup_audio_media_path")
    @mock.patch.object(audio, "pid_exists", return_value=False)
    def test_load_audio_playback_state_cleans_stale_process_session(
        self,
        _mock_exists: mock.MagicMock,
        mock_cleanup: mock.MagicMock,
        mock_clear: mock.MagicMock,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            media_path = os.path.join(temp_dir, "audio.m4a")
            with mock.patch.dict(os.environ, {"BILITERMINAL_STATE_DIR": temp_dir}, clear=False):
                cli.save_audio_playback_state(
                    cli.AudioPlaybackState(
                        pid=2345,
                        title="标题",
                        video_key="BV1xx411c7mu",
                        backend="macos-native",
                        paused=False,
                        control_pid=6789,
                        media_path=media_path,
                    )
                )
                state = cli.load_audio_playback_state()
        self.assertIsNone(state)
        mock_cleanup.assert_called_once_with(media_path)
        mock_clear.assert_called_once()


class ClientCredentialsTests(unittest.TestCase):
    def test_set_cookie_string(self) -> None:
        client = cli.BilibiliClient()
        client.cookie_jar.clear()
        client._set_cookie_string("SESSDATA=my_session_data; bili_jct=csrf_token; DedeUserID=123456")
        cookies = {c.name: c.value for c in client.cookie_jar}
        self.assertEqual(cookies.get("SESSDATA"), "my_session_data")
        self.assertEqual(cookies.get("bili_jct"), "csrf_token")
        self.assertEqual(cookies.get("DedeUserID"), "123456")

    def test_load_credentials_from_env_cookie(self) -> None:
        with mock.patch.dict(os.environ, {"BILITERMINAL_COOKIE": "SESSDATA=env_cookie_data"}):
            client = cli.BilibiliClient()
            cookies = {c.name: c.value for c in client.cookie_jar}
            self.assertEqual(cookies.get("SESSDATA"), "env_cookie_data")

    def test_load_credentials_from_env_sessdata(self) -> None:
        with mock.patch.dict(os.environ, {"BILITERMINAL_SESSDATA": "env_sessdata_only"}):
            client = cli.BilibiliClient()
            cookies = {c.name: c.value for c in client.cookie_jar}
            self.assertEqual(cookies.get("SESSDATA"), "env_sessdata_only")

    def test_load_credentials_from_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with mock.patch.dict(os.environ, {"BILITERMINAL_STATE_DIR": temp_dir}):
                cred_path = os.path.join(temp_dir, "credentials.json")
                with open(cred_path, "w", encoding="utf-8") as f:
                    json.dump({"cookie": "SESSDATA=file_cookie_data"}, f)
                client = cli.BilibiliClient()
                cookies = {c.name: c.value for c in client.cookie_jar}
                self.assertEqual(cookies.get("SESSDATA"), "file_cookie_data")

    def test_save_session(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with mock.patch.dict(os.environ, {"BILITERMINAL_STATE_DIR": temp_dir}):
                client = cli.BilibiliClient()
                client.cookie_jar.clear()
                client._set_cookie_string("SESSDATA=save_test_sessdata; bili_jct=save_test_csrf")
                client.save_session()

                cred_path = os.path.join(temp_dir, "credentials.json")
                self.assertTrue(os.path.exists(cred_path))
                with open(cred_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.assertIn("SESSDATA=save_test_sessdata", data.get("cookie", ""))
                self.assertEqual(data.get("SESSDATA"), "save_test_sessdata")

    def test_user_id_falls_back_to_nav_with_sessdata_only(self) -> None:
        client = cli.BilibiliClient()
        client.cookie_jar.clear()
        client._set_cookie_string("SESSDATA=env_sessdata_only")
        client._request_json = mock.MagicMock(return_value={"isLogin": True, "mid": 123456})

        self.assertEqual(client._get_user_id(), "123456")
        client._request_json.assert_called_once_with(
            "https://api.bilibili.com/x/web-interface/nav",
            {},
            "https://www.bilibili.com/",
        )


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
    def test_user_favorite_videos_uses_publish_time_not_favorite_time(self, mock_open: mock.MagicMock) -> None:
        mock_open.return_value = self.make_response(
            {
                "code": 0,
                "data": {
                    "medias": [
                        {
                            "title": "收藏视频",
                            "upper": {"name": "UP"},
                            "bvid": "BV1xx411c7mu",
                            "aid": 106,
                            "duration": 99,
                            "cnt_info": {"play": 10, "danmaku": 2, "collect": 5},
                            "pubtime": 1710000000,
                            "fav_time": 1810000000,
                            "intro": "简介",
                            "link": "https://www.bilibili.com/video/BV1xx411c7mu",
                        }
                    ],
                    "has_more": False,
                },
            }
        )

        items, has_more = cli.BilibiliClient().user_favorite_videos(10)

        self.assertFalse(has_more)
        self.assertEqual(items[0].title, "收藏视频")
        self.assertEqual(items[0].pubdate, 1710000000)
        self.assertEqual(items[0].favorite, 5)

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

    def test_audio_stream_for_item_parses_embedded_playinfo(self) -> None:
        client = cli.BilibiliClient()
        client._request_text = mock.MagicMock(
            return_value=(
                '<script>window.__playinfo__={"data":{"dash":{"audio":[{"bandwidth":96000,'
                '"baseUrl":"https://example.com/audio.m4s"}]}}}</script>'
            )
        )
        item = cli.VideoItem(
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
            description="简介",
            url="https://www.bilibili.com/video/BV1xx411c7mu",
            raw={},
        )
        stream = client.audio_stream_for_item(item)
        self.assertEqual(stream.url, "https://example.com/audio.m4s")
        self.assertEqual(stream.referer, item.url)

    def test_extract_video_stream_prefers_avc_backup_url(self) -> None:
        stream = cli.extract_video_stream(
            {
                "data": {
                    "dash": {
                        "video": [
                            {
                                "bandwidth": 200000,
                                "baseUrl": "https://example.com/av1.m4s",
                                "codecs": "av01.0.08M.08",
                                "width": 1920,
                                "height": 1080,
                            },
                            {
                                "bandwidth": 100000,
                                "backupUrl": ["https://example.com/avc-backup.m4s"],
                                "codecs": "avc1.640028",
                                "width": 1280,
                                "height": 720,
                            },
                        ]
                    }
                }
            },
            referer="https://www.bilibili.com/video/BV1xx411c7mu",
            user_agent="UA",
            cookie_header="SESSDATA=abc",
        )
        self.assertEqual(stream.url, "https://example.com/avc-backup.m4s")
        self.assertEqual(stream.codec, "avc1.640028")
        self.assertEqual(stream.cookie_header, "SESSDATA=abc")

    def test_video_stream_for_item_uses_canonical_referer_and_cookie(self) -> None:
        client = cli.BilibiliClient()
        client._set_cookie_string("SESSDATA=abc")
        client._request_text = mock.MagicMock(
            return_value=(
                '<script>window.__playinfo__={"data":{"dash":{"video":[{'
                '"bandwidth":96000,"baseUrl":"https://example.com/video.m4s",'
                '"codecs":"avc1.640028","width":640,"height":360'
                '}]}}}</script>'
            )
        )
        item = cli.VideoItem(
            title="收藏视频",
            author="UP",
            bvid="BV1xx411c7mu",
            aid=106,
            duration="1:00",
            play=1,
            danmaku=2,
            like=3,
            favorite=4,
            pubdate=1710000000,
            description="简介",
            url="bilibili://video/BV1xx411c7mu",
            raw={},
        )
        stream = client.video_stream_for_item(item)
        self.assertEqual(stream.referer, "https://www.bilibili.com/video/BV1xx411c7mu")
        self.assertIn("SESSDATA=abc", stream.cookie_header)
        client._request_text.assert_called_once_with(
            "https://www.bilibili.com/video/BV1xx411c7mu",
            "https://www.bilibili.com/",
        )

    @mock.patch.object(audio, "clear_audio_playback_state")
    @mock.patch.object(audio, "pid_exists", side_effect=[True, False])
    @mock.patch.object(audio, "wait_for_audio_exit")
    @mock.patch.object(audio, "send_audio_signal")
    @mock.patch.object(audio, "load_audio_playback_state")
    def test_stop_audio_playback_terminates_current_session(
        self,
        mock_load: mock.MagicMock,
        mock_signal: mock.MagicMock,
        _mock_wait: mock.MagicMock,
        _mock_exists: mock.MagicMock,
        mock_clear: mock.MagicMock,
    ) -> None:
        mock_load.return_value = cli.AudioPlaybackState(pid=4321, title="标题", video_key="BV1xx411c7mu", paused=False)
        message = cli.stop_audio_playback()
        mock_signal.assert_called_once()
        mock_clear.assert_called_once()
        self.assertIn("已停止音频", message)

    @mock.patch.object(audio, "cleanup_audio_media_path")
    @mock.patch.object(audio, "clear_audio_playback_state")
    @mock.patch.object(audio, "pid_exists", side_effect=[True, True, False])
    @mock.patch.object(audio, "wait_for_audio_exit")
    @mock.patch.object(audio, "send_audio_signal")
    @mock.patch.object(audio, "load_audio_playback_state")
    def test_stop_audio_playback_cleans_media_path_for_process_backend(
        self,
        mock_load: mock.MagicMock,
        mock_signal: mock.MagicMock,
        _mock_wait: mock.MagicMock,
        _mock_exists: mock.MagicMock,
        mock_clear: mock.MagicMock,
        mock_cleanup: mock.MagicMock,
    ) -> None:
        mock_load.return_value = cli.AudioPlaybackState(
            pid=4321,
            title="标题",
            video_key="BV1xx411c7mu",
            backend="macos-native",
            paused=False,
            control_pid=8765,
            media_path="/tmp/audio.m4a",
        )
        message = cli.stop_audio_playback()
        self.assertEqual(mock_signal.call_count, 2)
        self.assertEqual(mock_signal.call_args_list[0].args, (8765, cli.signal.SIGTERM))
        self.assertEqual(mock_signal.call_args_list[1].args, (4321, cli.signal.SIGTERM))
        mock_cleanup.assert_called_once_with("/tmp/audio.m4a")
        mock_clear.assert_called_once()
        self.assertIn("已停止音频", message)

    @mock.patch.object(audio, "save_audio_playback_state")
    @mock.patch.object(audio, "send_audio_signal")
    @mock.patch.object(audio, "load_audio_playback_state")
    def test_pause_audio_playback_uses_helper_pause_signal_for_macos_native(
        self,
        mock_load: mock.MagicMock,
        mock_signal: mock.MagicMock,
        mock_save: mock.MagicMock,
    ) -> None:
        state = cli.AudioPlaybackState(
            pid=4321,
            title="标题",
            video_key="BV1xx411c7mu",
            backend="macos-native",
            paused=False,
            control_pid=8765,
            media_path="/tmp/audio.m4a",
        )
        mock_load.return_value = state
        message = cli.pause_audio_playback()
        mock_signal.assert_called_once_with(8765, cli.signal.SIGUSR1)
        self.assertTrue(state.paused)
        mock_save.assert_called_once_with(state)
        self.assertIn("已暂停音频", message)

    @mock.patch.object(audio, "save_audio_playback_state")
    @mock.patch.object(audio, "send_audio_signal")
    @mock.patch.object(audio, "load_audio_playback_state")
    def test_resume_audio_playback_uses_helper_resume_signal_for_macos_native(
        self,
        mock_load: mock.MagicMock,
        mock_signal: mock.MagicMock,
        mock_save: mock.MagicMock,
    ) -> None:
        state = cli.AudioPlaybackState(
            pid=4321,
            title="标题",
            video_key="BV1xx411c7mu",
            backend="macos-native",
            paused=True,
            control_pid=8765,
            media_path="/tmp/audio.m4a",
        )
        mock_load.return_value = state
        message = cli.resume_audio_playback()
        mock_signal.assert_called_once_with(8765, cli.signal.SIGUSR2)
        self.assertFalse(state.paused)
        mock_save.assert_called_once_with(state)
        self.assertIn("已继续播放音频", message)

    @mock.patch.object(audio, "save_audio_playback_state")
    @mock.patch.object(audio, "load_audio_playback_state")
    @mock.patch.object(audio, "macos_audio_helper_path", return_value="/tmp/biliterminal-audio-helper")
    @mock.patch.object(audio.shutil, "which", return_value=None)
    @mock.patch.object(audio.subprocess, "Popen")
    def test_run_audio_worker_streams_via_macos_native_helper(
        self,
        mock_popen: mock.MagicMock,
        _mock_which: mock.MagicMock,
        _mock_helper_path: mock.MagicMock,
        mock_load: mock.MagicMock,
        mock_save: mock.MagicMock,
    ) -> None:
        helper_process = mock.MagicMock()
        helper_process.pid = 9988
        helper_process.wait.return_value = 0
        mock_popen.return_value = helper_process
        mock_load.return_value = cli.AudioPlaybackState(pid=4321, title="标题", video_key="BV1xx411c7mu")
        result = cli.run_audio_worker("https://example.com/audio.m4s", "https://www.bilibili.com/video/BV1", "UA", "标题")
        self.assertEqual(result, 0)
        mock_popen.assert_called_once_with(
            [
                "/tmp/biliterminal-audio-helper",
                "--stream",
                "https://example.com/audio.m4s",
                "https://www.bilibili.com/video/BV1",
                "UA",
                "audio/mp4",
            ],
            stdout=cli.subprocess.DEVNULL,
            stderr=cli.subprocess.DEVNULL,
            stdin=cli.subprocess.DEVNULL,
        )
        saved_state = mock_save.call_args.args[0]
        self.assertEqual(saved_state.title, "标题")
        self.assertEqual(saved_state.video_key, "BV1xx411c7mu")
        self.assertEqual(saved_state.backend, "macos-native")
        self.assertIsNone(saved_state.media_path)
        self.assertEqual(saved_state.pid, os.getpid())
        self.assertEqual(saved_state.control_pid, helper_process.pid)

    @mock.patch.object(audio, "cleanup_audio_media_path")
    @mock.patch.object(audio, "save_audio_playback_state")
    @mock.patch.object(audio, "load_audio_playback_state")
    @mock.patch.object(audio, "download_audio_to_path")
    @mock.patch.object(audio, "prepare_audio_temp_path", return_value="/tmp/audio.m4a")
    @mock.patch.object(audio, "macos_audio_helper_path", return_value="/tmp/biliterminal-audio-helper")
    @mock.patch.object(audio.shutil, "which", return_value=None)
    @mock.patch.object(audio.subprocess, "Popen")
    def test_run_audio_worker_falls_back_to_download_when_stream_fails(
        self,
        mock_popen: mock.MagicMock,
        _mock_which: mock.MagicMock,
        _mock_helper_path: mock.MagicMock,
        _mock_prepare_path: mock.MagicMock,
        mock_download: mock.MagicMock,
        mock_load: mock.MagicMock,
        _mock_save: mock.MagicMock,
        mock_cleanup: mock.MagicMock,
    ) -> None:
        stream_process = mock.MagicMock()
        stream_process.pid = 9988
        stream_process.wait.return_value = 1
        file_process = mock.MagicMock()
        file_process.pid = 9989
        file_process.wait.return_value = 0
        mock_popen.side_effect = [stream_process, file_process]
        mock_load.return_value = cli.AudioPlaybackState(pid=os.getpid(), title="标题", video_key="BV1xx411c7mu")
        result = cli.run_audio_worker("https://example.com/audio.m4s", "https://www.bilibili.com/video/BV1", "UA", "标题")
        self.assertEqual(result, 0)
        mock_download.assert_called_once()
        self.assertEqual(mock_popen.call_count, 2)
        self.assertEqual(
            mock_popen.call_args_list[1].args[0],
            ["/tmp/biliterminal-audio-helper", "/tmp/audio.m4a"],
        )
        mock_cleanup.assert_called_once_with("/tmp/audio.m4a")

    @mock.patch.object(audio, "save_audio_playback_state")
    @mock.patch.object(audio, "load_audio_playback_state")
    @mock.patch.object(audio.subprocess, "Popen")
    def test_run_audio_worker_uses_direct_video_key_without_state_read(
        self,
        mock_popen: mock.MagicMock,
        mock_load: mock.MagicMock,
        mock_save: mock.MagicMock,
    ) -> None:
        player = mock.MagicMock()
        player.pid = 4242
        player.wait.return_value = 0
        mock_popen.return_value = player
        with tempfile.TemporaryDirectory() as temp_dir:
            with mock.patch.dict(os.environ, {"BILITERMINAL_STATE_DIR": temp_dir}, clear=False):
                with mock.patch.object(audio.shutil, "which", side_effect=lambda name: "/usr/local/bin/mpv" if name == "mpv" else None):
                    result = cli.run_audio_worker(
                        "https://example.com/audio.m4s", "https://www.bilibili.com/video/BV1", "UA", "标题",
                        video_key="BV1xx411c7mu",
                    )
        self.assertEqual(result, 0)
        mock_load.assert_not_called()
        saved_state = mock_save.call_args.args[0]
        self.assertEqual(saved_state.video_key, "BV1xx411c7mu")
        self.assertEqual(saved_state.control_pid, 4242)
        self.assertIsNotNone(saved_state.ipc_socket)
        command = mock_popen.call_args.args[0]
        self.assertEqual(command[0], "mpv")
        self.assertIn(f"--input-ipc-server={saved_state.ipc_socket}", command)

    @mock.patch.object(audio, "save_audio_playback_state")
    @mock.patch.object(audio, "send_audio_signal")
    @mock.patch.object(audio, "set_mpv_paused", return_value=True)
    @mock.patch.object(audio, "load_audio_playback_state")
    def test_pause_audio_playback_prefers_mpv_ipc(
        self,
        mock_load: mock.MagicMock,
        mock_ipc: mock.MagicMock,
        mock_signal: mock.MagicMock,
        mock_save: mock.MagicMock,
    ) -> None:
        state = cli.AudioPlaybackState(
            pid=4321,
            title="标题",
            video_key="BV1xx411c7mu",
            backend="process",
            paused=False,
            control_pid=8765,
            ipc_socket="/tmp/mpv.sock",
        )
        mock_load.return_value = state
        message = cli.pause_audio_playback()
        mock_ipc.assert_called_once_with(state, True)
        mock_signal.assert_not_called()
        self.assertTrue(state.paused)
        mock_save.assert_called_once_with(state)
        self.assertIn("已暂停音频", message)

    @mock.patch.object(audio, "save_audio_playback_state")
    @mock.patch.object(audio, "send_audio_signal")
    @mock.patch.object(audio, "set_mpv_paused", return_value=False)
    @mock.patch.object(audio, "load_audio_playback_state")
    def test_pause_audio_playback_falls_back_to_signal_without_ipc(
        self,
        mock_load: mock.MagicMock,
        _mock_ipc: mock.MagicMock,
        mock_signal: mock.MagicMock,
        mock_save: mock.MagicMock,
    ) -> None:
        state = cli.AudioPlaybackState(
            pid=4321,
            title="标题",
            video_key="BV1xx411c7mu",
            backend="process",
            paused=False,
            control_pid=8765,
        )
        mock_load.return_value = state
        cli.pause_audio_playback()
        mock_signal.assert_called_once_with(8765, cli.signal.SIGSTOP)
        self.assertTrue(state.paused)
        mock_save.assert_called_once_with(state)


class VideoPlayerTests(unittest.TestCase):
    def make_stream(self, cookie_header: str = "") -> cli.VideoStream:
        return cli.VideoStream(
            url="https://example.com/video.m4s",
            referer="https://www.bilibili.com/video/BV1xx411c7mu",
            user_agent="UA",
            width=640,
            height=360,
            frame_rate="30",
            codec="avc1",
            bandwidth=100000,
            source_kind="dash-video",
            cookie_header=cookie_header,
        )

    def test_ffmpeg_command_includes_headers_but_log_redacts_cookie(self) -> None:
        command = vp._build_ffmpeg_command(self.make_stream("SESSDATA=secret"), 40, 12, fps=8)
        self.assertIn("Cookie: SESSDATA=secret", command[command.index("-headers") + 1])
        redacted = " ".join(vp._redact_ffmpeg_command(command))
        self.assertIn("Cookie: <redacted>", redacted)
        self.assertNotIn("secret", redacted)

    def test_stop_wakes_paused_process_and_closes_stderr(self) -> None:
        class FakeProcess:
            def __init__(self) -> None:
                self.signals: list[int] = []
                self.returncode = None

            def poll(self) -> int | None:
                return None

            def send_signal(self, sig: int) -> None:
                self.signals.append(sig)

            def wait(self, timeout: float | None = None) -> int:
                self.returncode = -15
                return self.returncode

            def kill(self) -> None:
                self.signals.append(cli.signal.SIGKILL)

        process = FakeProcess()
        player = vp.VideoPlayer(self.make_stream(), 40, 12, fps=8)
        player._process = process
        player._paused = True
        stderr_handle = mock.MagicMock()
        player._stderr_handle = stderr_handle
        player.stop()
        self.assertEqual(process.signals[:2], [cli.signal.SIGCONT, cli.signal.SIGTERM])
        stderr_handle.close.assert_called_once()
        self.assertIsNone(player._stderr_handle)

    def test_render_frame_rejects_short_frame(self) -> None:
        with self.assertRaises(ValueError):
            vp.render_frame(b"\xff\xff", 1, 1)
        self.assertEqual(vp.render_frame(b"", 0, 1), "")


class ShellTests(unittest.TestCase):
    def make_store(self) -> cli.HistoryStore:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        return cli.HistoryStore(path=f"{temp_dir.name}/history.json")

    def test_parser_supports_history_command(self) -> None:
        args = cli.build_parser().parse_args(["history"])
        self.assertEqual(args.command, "history")

    def test_parser_supports_favorite_command(self) -> None:
        args = cli.build_parser().parse_args(["favorite", "BV1xx411c7mu"])
        self.assertEqual(args.command, "favorite")

    def test_parser_supports_favorites_open_command(self) -> None:
        args = cli.build_parser().parse_args(["favorites", "open", "1"])
        self.assertEqual(args.command, "favorites")
        self.assertEqual(args.favorites_action, "open")

    def test_parser_supports_tui_command(self) -> None:
        args = cli.build_parser().parse_args(["tui"])
        self.assertEqual(args.command, "tui")

    def test_parser_supports_recommend_command(self) -> None:
        args = cli.build_parser().parse_args(["recommend"])
        self.assertEqual(args.command, "recommend")

    def test_parser_supports_comments_command(self) -> None:
        args = cli.build_parser().parse_args(["comments", "BV1xx411c7mu"])
        self.assertEqual(args.command, "comments")

    def test_parser_supports_audio_command(self) -> None:
        args = cli.build_parser().parse_args(["audio", "BV1xx411c7mu"])
        self.assertEqual(args.command, "audio")

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

    @mock.patch.object(audio, "play_audio_for_item")
    def test_do_audio_by_index_uses_last_results(self, mock_play_audio: mock.MagicMock) -> None:
        mock_play_audio.return_value = "已开始播放音频: 标题"
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
        with mock.patch("sys.stdout", new=io.StringIO()) as stdout:
            shell.do_audio("1")
        mock_play_audio.assert_called_once()
        self.assertIn("已开始播放音频", stdout.getvalue())

    @mock.patch.object(audio, "stop_audio_playback")
    def test_do_audio_stop_uses_audio_control(self, mock_stop_audio: mock.MagicMock) -> None:
        mock_stop_audio.return_value = "已停止音频: 标题"
        shell = cli.BilibiliCLI(cli.BilibiliClient(), self.make_store())
        with mock.patch("sys.stdout", new=io.StringIO()) as stdout:
            shell.do_audio("stop")
        mock_stop_audio.assert_called_once()
        self.assertIn("已停止音频", stdout.getvalue())

    def test_resolve_favorite_item_by_index(self) -> None:
        shell = cli.BilibiliCLI(cli.BilibiliClient(), self.make_store())
        item = cli.VideoItem(
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
        shell.history_store.add_favorite(item)
        self.assertEqual(shell._resolve_favorite_item("1").bvid, "BV1xx411c7mu")


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

    def test_default_history_path_uses_explicit_state_dir_env(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with mock.patch.dict(os.environ, {"BILITERMINAL_STATE_DIR": temp_dir}, clear=False):
                self.assertEqual(
                    cli.default_history_path(),
                    os.path.join(temp_dir, "bilibili-cli-history.json"),
                )

    def test_default_history_path_uses_home_dir_env(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with mock.patch.dict(os.environ, {"BILITERMINAL_HOME": temp_dir}, clear=False):
                self.assertEqual(
                    cli.default_history_path(),
                    os.path.join(temp_dir, "state", "bilibili-cli-history.json"),
                )

    def test_history_store_uses_dynamic_default_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with mock.patch.dict(os.environ, {"BILITERMINAL_HOME": temp_dir}, clear=False):
                store = cli.HistoryStore()
                self.assertEqual(
                    store.path,
                    os.path.join(temp_dir, "state", "bilibili-cli-history.json"),
                )

    def test_history_store_persists_favorites(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = f"{temp_dir}/history.json"
            store = cli.HistoryStore(path=path)
            store.add_favorite(self.make_item("收藏视频"))

            reloaded = cli.HistoryStore(path=path)
            self.assertEqual(reloaded.get_favorite_videos(1)[0].title, "收藏视频")

    def test_history_store_remove_favorite(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = cli.HistoryStore(path=f"{temp_dir}/history.json")
            item = self.make_item("收藏视频")
            store.add_favorite(item)
            self.assertTrue(store.remove_favorite(item))
            self.assertEqual(store.get_favorite_videos(), [])

    def test_history_store_toggle_favorite(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = cli.HistoryStore(path=f"{temp_dir}/history.json")
            item = self.make_item("收藏视频")
            self.assertTrue(store.toggle_favorite(item))
            self.assertTrue(store.is_favorite(item))
            self.assertFalse(store.toggle_favorite(item))
            self.assertFalse(store.is_favorite(item))

    def test_replace_favorites_persists_all_synced_items_beyond_local_limit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = f"{temp_dir}/history.json"
            items = [
                self.make_item(f"收藏视频 {index}", f"BV1xx411c7m{index}")
                for index in range(3)
            ]
            store = cli.HistoryStore(path=path, max_favorites=2)
            self.assertEqual(store.replace_favorites(items), 3)

            reloaded = cli.HistoryStore(path=path, max_favorites=2)
            self.assertEqual(
                [item.title for item in reloaded.get_favorite_videos()],
                ["收藏视频 0", "收藏视频 1", "收藏视频 2"],
            )


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

    def test_load_items_uses_favorites_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = cli.HistoryStore(path=f"{temp_dir}/history.json")
            store.add_favorite(self.make_item("收藏稿件"))
            tui = cli.BilibiliTUI(cli.BilibiliClient(), store)
            tui.mode = "favorites"
            tui.load_items()
            self.assertEqual(len(tui.items), 1)
            self.assertEqual(tui.items[0].title, "收藏稿件")

    def test_init_theme_prefers_bilibili_pink(self) -> None:
        class FakeCurses:
            COLOR_BLACK = 0
            COLOR_WHITE = 7
            COLOR_MAGENTA = 5
            COLOR_CYAN = 6
            COLOR_YELLOW = 3
            COLOR_GREEN = 2
            COLOR_RED = 1
            COLORS = 16
            error = RuntimeError

            def __init__(self) -> None:
                self.calls: list[tuple[object, ...]] = []

            def has_colors(self) -> bool:
                return True

            def start_color(self) -> None:
                self.calls.append(("start_color",))

            def use_default_colors(self) -> None:
                self.calls.append(("use_default_colors",))

            def can_change_color(self) -> bool:
                return True

            def init_color(self, color: int, r: int, g: int, b: int) -> None:
                self.calls.append(("init_color", color, r, g, b))

            def init_pair(self, pair: int, fg: int, bg: int) -> None:
                self.calls.append(("init_pair", pair, fg, bg))

        with tempfile.TemporaryDirectory() as temp_dir:
            fake_curses = FakeCurses()
            store = cli.HistoryStore(path=f"{temp_dir}/history.json")
            tui = cli.BilibiliTUI(cli.BilibiliClient(), store)
            with mock.patch.dict(sys.modules, {"curses": fake_curses}):
                tui.init_theme()
            self.assertIn(("init_color", 13, *cli.BILIBILI_PINK_RGB), fake_curses.calls)
            # 品牌/选中都用粉色前景 + 透明背景，不再铺实心色块
            self.assertIn(("init_pair", 1, 13, -1), fake_curses.calls)
            self.assertIn(("init_pair", 4, 13, -1), fake_curses.calls)
            self.assertTrue(tui.use_colors)

    def test_run_shortens_curses_escape_delay(self) -> None:
        class FakeCurses:
            KEY_RESIZE = 410
            error = RuntimeError

            def __init__(self) -> None:
                self.escdelay: int | None = None

            def set_escdelay(self, delay_ms: int) -> None:
                self.escdelay = delay_ms

            def curs_set(self, _visibility: int) -> None:
                return None

        class FakeScreen:
            def keypad(self, _enabled: bool) -> None:
                return None

            def timeout(self, _delay: int) -> None:
                return None

            def getch(self) -> int:
                return ord("q")

        with tempfile.TemporaryDirectory() as temp_dir:
            fake_curses = FakeCurses()
            store = cli.HistoryStore(path=f"{temp_dir}/history.json")
            tui = cli.BilibiliTUI(cli.BilibiliClient(), store)
            tui.init_theme = mock.MagicMock()
            tui.start_load_items = mock.MagicMock()
            tui.draw = mock.MagicMock()
            with mock.patch.dict(sys.modules, {"curses": fake_curses}):
                tui.run(FakeScreen())
            self.assertEqual(fake_curses.escdelay, tui_module.ESCDELAY_MS)

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
            tui.start_load_items = mock.MagicMock()
            tui.set_channel(3, push_current=False)
            self.assertEqual(tui.channel_index, 3)
            tui.start_load_items.assert_called_once()

    def test_restore_previous_state_returns_to_search(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = cli.HistoryStore(path=f"{temp_dir}/history.json")
            tui = cli.BilibiliTUI(cli.BilibiliClient(), store)
            tui.start_load_items = mock.MagicMock()
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
            tui.start_load_items.assert_called_once()

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

    def test_toggle_selected_favorite_adds_item(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = cli.HistoryStore(path=f"{temp_dir}/history.json")
            tui = cli.BilibiliTUI(cli.BilibiliClient(), store)
            tui.items = [self.make_item("收藏目标")]
            tui.toggle_selected_favorite()
            self.assertEqual(store.get_favorite_videos(1)[0].title, "收藏目标")
            self.assertIn("已收藏", tui.status)

    def test_toggle_selected_favorite_refreshes_favorites_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = cli.HistoryStore(path=f"{temp_dir}/history.json")
            item = self.make_item("收藏目标")
            store.add_favorite(item)
            tui = cli.BilibiliTUI(cli.BilibiliClient(), store)
            tui.mode = "favorites"
            tui.items = [item]
            tui.load_items = mock.MagicMock()
            tui.toggle_selected_favorite()
            tui.load_items.assert_called_once()
            self.assertIn("已取消收藏", tui.status)

    @mock.patch.object(audio, "play_audio_for_item")
    def test_play_selected_audio_updates_status(self, mock_play_audio: mock.MagicMock) -> None:
        mock_play_audio.return_value = "已开始播放音频: 标题"
        with tempfile.TemporaryDirectory() as temp_dir:
            store = cli.HistoryStore(path=f"{temp_dir}/history.json")
            tui = cli.BilibiliTUI(cli.BilibiliClient(), store)
            tui.items = [self.make_item()]
            tui.play_selected_audio()
            mock_play_audio.assert_called_once()
            self.assertEqual(tui.status, "已开始播放音频: 标题")

    @mock.patch.object(audio, "toggle_audio_playback")
    @mock.patch.object(audio, "load_audio_playback_state")
    @mock.patch.object(audio, "play_audio_for_item")
    def test_play_selected_audio_toggles_when_same_item_is_playing(
        self,
        mock_play_audio: mock.MagicMock,
        mock_load_state: mock.MagicMock,
        mock_toggle: mock.MagicMock,
    ) -> None:
        mock_load_state.return_value = cli.AudioPlaybackState(
            pid=1234,
            title="标题",
            video_key="BV1xx411c7mu",
            paused=False,
        )
        mock_toggle.return_value = "已暂停音频: 标题"
        with tempfile.TemporaryDirectory() as temp_dir:
            store = cli.HistoryStore(path=f"{temp_dir}/history.json")
            tui = cli.BilibiliTUI(cli.BilibiliClient(), store)
            tui.items = [self.make_item()]
            tui.play_selected_audio()
        mock_toggle.assert_called_once()
        mock_play_audio.assert_not_called()
        self.assertEqual(tui.status, "已暂停音频: 标题")

    @mock.patch.object(audio, "stop_audio_playback")
    def test_stop_audio_updates_status(self, mock_stop_audio: mock.MagicMock) -> None:
        mock_stop_audio.return_value = "已停止音频: 标题"
        with tempfile.TemporaryDirectory() as temp_dir:
            store = cli.HistoryStore(path=f"{temp_dir}/history.json")
            tui = cli.BilibiliTUI(cli.BilibiliClient(), store)
            tui.stop_audio()
            mock_stop_audio.assert_called_once()
            self.assertEqual(tui.status, "已停止音频: 标题")

    def test_video_stream_failure_returns_to_tui_and_preserves_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = cli.HistoryStore(path=f"{temp_dir}/history.json")
            tui = cli.BilibiliTUI(cli.BilibiliClient(), store)
            tui.items = [self.make_item()]
            tui._submit = lambda work, apply, status=None: apply(work())
            tui.client.video_stream_for_item = mock.MagicMock(side_effect=cli.BilibiliAPIError("boom"))
            with mock.patch.object(vp, "has_ffmpeg", return_value=True), mock.patch("sys.stdout", new=io.StringIO()):
                tui.enter_video_mode()
            self.assertFalse(tui.video_mode)
            self.assertEqual(tui._video_state, "failed")
            self.assertIn("boom", tui.status)

    @mock.patch.object(audio, "play_audio_for_item", side_effect=cli.BilibiliAPIError("audio fail"))
    def test_video_audio_start_failure_does_not_crash_or_exit_video(self, _mock_audio: mock.MagicMock) -> None:
        class FakePlayer:
            def start(self) -> None:
                return None

            def stop(self) -> None:
                return None

        stream = cli.VideoStream(
            url="https://example.com/video.m4s",
            referer="https://www.bilibili.com/video/BV1xx411c7mu",
            user_agent="UA",
            width=640,
            height=360,
            frame_rate="30",
            codec="avc1",
            bandwidth=100000,
            source_kind="dash-video",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            store = cli.HistoryStore(path=f"{temp_dir}/history.json")
            tui = cli.BilibiliTUI(cli.BilibiliClient(), store)
            tui.items = [self.make_item()]
            tui._submit = lambda work, apply, status=None: apply(work())
            tui.client.video_stream_for_item = mock.MagicMock(return_value=stream)
            with mock.patch.object(vp, "has_ffmpeg", return_value=True), mock.patch.object(vp, "VideoPlayer", return_value=FakePlayer()):
                tui.enter_video_mode()
            self.assertTrue(tui.video_mode)
            self.assertEqual(tui._video_state, "playing")
            self.assertFalse(tui._video_started_audio)
            self.assertIn("音频启动失败", tui.status)

    @mock.patch.object(audio, "stop_audio_playback")
    def test_video_q_returns_to_tui_without_exiting_app(self, mock_stop: mock.MagicMock) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = cli.HistoryStore(path=f"{temp_dir}/history.json")
            tui = cli.BilibiliTUI(cli.BilibiliClient(), store)
            tui.video_mode = True
            tui._video_started_audio = True
            tui._video_player = mock.MagicMock()
            with mock.patch("sys.stdout", new=io.StringIO()):
                should_exit = tui.handle_video_key(ord("q"))
            self.assertFalse(should_exit)
            self.assertFalse(tui.video_mode)
            mock_stop.assert_called_once_with(silent=True)

    @mock.patch.object(audio, "stop_audio_playback")
    def test_video_esc_returns_to_tui_and_requests_full_redraw(self, mock_stop: mock.MagicMock) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = cli.HistoryStore(path=f"{temp_dir}/history.json")
            tui = cli.BilibiliTUI(cli.BilibiliClient(), store)
            tui.video_mode = True
            tui._video_started_audio = True
            tui._video_player = mock.MagicMock()
            stdout = io.StringIO()
            with mock.patch("sys.stdout", new=stdout):
                should_exit = tui.handle_video_key(27)
            self.assertFalse(should_exit)
            self.assertFalse(tui.video_mode)
            self.assertTrue(tui._force_full_redraw)
            self.assertIn("\x1b(B\x1b[2J\x1b[H", stdout.getvalue())
            mock_stop.assert_called_once_with(silent=True)

    @mock.patch.object(audio, "stop_audio_playback")
    def test_video_x_stops_and_returns_to_tui(self, mock_stop: mock.MagicMock) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = cli.HistoryStore(path=f"{temp_dir}/history.json")
            tui = cli.BilibiliTUI(cli.BilibiliClient(), store)
            tui.video_mode = True
            tui._video_started_audio = True
            tui._video_player = mock.MagicMock()
            with mock.patch("sys.stdout", new=io.StringIO()):
                tui.handle_video_key(ord("x"))
            self.assertFalse(tui.video_mode)
            self.assertEqual(tui.status, "已停止播放")
            mock_stop.assert_called_once_with(silent=True)

    @mock.patch.object(audio, "pause_audio_playback", return_value="已暂停音频: 标题")
    def test_video_space_pauses_video_and_audio(self, mock_pause: mock.MagicMock) -> None:
        player = mock.MagicMock()
        player.toggle_pause.return_value = False
        with tempfile.TemporaryDirectory() as temp_dir:
            store = cli.HistoryStore(path=f"{temp_dir}/history.json")
            tui = cli.BilibiliTUI(cli.BilibiliClient(), store)
            tui.video_mode = True
            tui._video_started_audio = True
            tui._video_player = player
            tui.handle_video_key(ord(" "))
            mock_pause.assert_called_once()
            self.assertEqual(tui._video_state, "paused")
            self.assertEqual(tui.status, "已暂停")

    @mock.patch.object(audio, "stop_audio_playback")
    def test_video_natural_end_cleans_up_once(self, mock_stop: mock.MagicMock) -> None:
        class FakePlayer:
            def __init__(self) -> None:
                self.stop_count = 0

            def get_frame(self) -> str:
                return "@"

            def is_alive(self) -> bool:
                return False

            def stop(self) -> None:
                self.stop_count += 1

        player = FakePlayer()
        with tempfile.TemporaryDirectory() as temp_dir:
            store = cli.HistoryStore(path=f"{temp_dir}/history.json")
            tui = cli.BilibiliTUI(cli.BilibiliClient(), store)
            tui.video_mode = True
            tui._video_state = "playing"
            tui._video_started_audio = True
            tui._video_player = player
            with mock.patch("sys.stdout", new=io.StringIO()):
                tui._tick()
                tui._tick()
            self.assertFalse(tui.video_mode)
            self.assertEqual(player.stop_count, 1)
            mock_stop.assert_called_once_with(silent=True)

    @mock.patch.object(audio, "stop_audio_playback")
    def test_video_process_exit_before_first_frame_returns_to_tui(self, mock_stop: mock.MagicMock) -> None:
        class FakePlayer:
            def get_frame(self) -> None:
                return None

            def is_alive(self) -> bool:
                return False

            def stop(self) -> None:
                return None

        with tempfile.TemporaryDirectory() as temp_dir:
            store = cli.HistoryStore(path=f"{temp_dir}/history.json")
            tui = cli.BilibiliTUI(cli.BilibiliClient(), store)
            tui.video_mode = True
            tui._video_state = "playing"
            tui._video_started_audio = True
            tui._video_player = FakePlayer()
            with mock.patch("sys.stdout", new=io.StringIO()):
                tui._tick()
            self.assertFalse(tui.video_mode)
            self.assertIn("视频播放失败", tui.status)
            mock_stop.assert_called_once_with(silent=True)

    def test_mode_token_uses_favorites_label(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = cli.HistoryStore(path=f"{temp_dir}/history.json")
            tui = cli.BilibiliTUI(cli.BilibiliClient(), store)
            tui.mode = "favorites"
            self.assertEqual(tui.mode_token(), "收藏夹")

    def test_draw_featured_card_compact_marks_favorite(self) -> None:
        import curses

        class FakeScreen:
            def __init__(self) -> None:
                self.lines: list[str] = []

            def derwin(self, *_args, **_kwargs) -> "FakeScreen":
                return self

            def box(self) -> None:
                return None

            def addch(self, *_args, **_kwargs) -> None:
                return None

            def hline(self, *_args, **_kwargs) -> None:
                return None

            def vline(self, *_args, **_kwargs) -> None:
                return None

            def addnstr(self, _y: int, _x: int, text: str, *_args) -> None:
                self.lines.append(text)

            def addstr(self, _y: int, _x: int, text: str, *_args) -> None:
                self.lines.append(text)

        with tempfile.TemporaryDirectory() as temp_dir:
            store = cli.HistoryStore(path=f"{temp_dir}/history.json")
            item = self.make_item("收藏卡片")
            store.add_favorite(item)
            tui = cli.BilibiliTUI(cli.BilibiliClient(), store)
            fake = FakeScreen()
            with mock.patch.object(curses, "ACS_HLINE", "-", create=True), \
                 mock.patch.object(curses, "ACS_VLINE", "|", create=True), \
                 mock.patch.object(curses, "ACS_ULCORNER", "+", create=True), \
                 mock.patch.object(curses, "ACS_URCORNER", "+", create=True), \
                 mock.patch.object(curses, "ACS_LLCORNER", "+", create=True), \
                 mock.patch.object(curses, "ACS_LRCORNER", "+", create=True):
                tui.draw_featured_card(fake, 0, 0, 8, 40, item, selected=False)
            rendered = " ".join(fake.lines)
            self.assertIn("✦ 收藏卡片", rendered)

    def test_draw_uses_favorites_view_in_favorites_mode(self) -> None:
        import curses

        class FakeScreen:
            def erase(self) -> None:
                return None

            def getmaxyx(self) -> tuple[int, int]:
                return (32, 120)

            def addnstr(self, *_args, **_kwargs) -> None:
                return None

            def hline(self, *_args, **_kwargs) -> None:
                return None

            def refresh(self) -> None:
                return None

        with tempfile.TemporaryDirectory() as temp_dir:
            store = cli.HistoryStore(path=f"{temp_dir}/history.json")
            tui = cli.BilibiliTUI(cli.BilibiliClient(), store)
            tui.mode = "favorites"
            tui.draw_favorites_view = mock.MagicMock()
            tui.draw_split_view = mock.MagicMock()
            with mock.patch.object(curses, "ACS_HLINE", "-", create=True):
                tui.draw(FakeScreen())
            tui.draw_favorites_view.assert_called_once()
            tui.draw_split_view.assert_not_called()

    def test_draw_favorites_mode_renders_sync_shortcut_hint(self) -> None:
        import curses

        class FakeScreen:
            def __init__(self) -> None:
                self.lines: list[str] = []

            def erase(self) -> None:
                return None

            def getmaxyx(self) -> tuple[int, int]:
                return (32, 160)

            def addnstr(self, _y: int, _x: int, text: str, *_args) -> None:
                self.lines.append(text)

            def hline(self, *_args, **_kwargs) -> None:
                return None

            def refresh(self) -> None:
                return None

        with tempfile.TemporaryDirectory() as temp_dir:
            store = cli.HistoryStore(path=f"{temp_dir}/history.json")
            tui = cli.BilibiliTUI(cli.BilibiliClient(), store)
            tui.mode = "favorites"
            tui.draw_favorites_view = mock.MagicMock()
            with mock.patch.object(curses, "ACS_HLINE", "-", create=True):
                fake = FakeScreen()
                tui.draw(fake)
            rendered = " ".join(fake.lines)
            self.assertIn("y 同步", rendered)

    def test_draw_tab_row_favorites_mode_renders_sync_hint(self) -> None:
        class FakeScreen:
            def __init__(self) -> None:
                self.lines: list[str] = []

            def addnstr(self, _y: int, _x: int, text: str, *_args) -> None:
                self.lines.append(text)

        with tempfile.TemporaryDirectory() as temp_dir:
            store = cli.HistoryStore(path=f"{temp_dir}/history.json")
            tui = cli.BilibiliTUI(cli.BilibiliClient(), store)
            tui.mode = "favorites"
            fake = FakeScreen()
            tui._draw_tab_row(fake, 0, 120)
            rendered = " ".join(fake.lines)
            self.assertIn("y 同步", rendered)

    def test_draw_after_video_exit_forces_curses_full_repaint(self) -> None:
        import curses

        class FakeScreen:
            def __init__(self) -> None:
                self.calls: list[tuple[object, ...]] = []

            def clearok(self, enabled: bool) -> None:
                self.calls.append(("clearok", enabled))

            def clear(self) -> None:
                self.calls.append(("clear",))

            def erase(self) -> None:
                self.calls.append(("erase",))

            def getmaxyx(self) -> tuple[int, int]:
                return (32, 120)

            def addnstr(self, *_args, **_kwargs) -> None:
                return None

            def hline(self, *_args, **_kwargs) -> None:
                return None

            def refresh(self) -> None:
                return None

        with tempfile.TemporaryDirectory() as temp_dir:
            store = cli.HistoryStore(path=f"{temp_dir}/history.json")
            tui = cli.BilibiliTUI(cli.BilibiliClient(), store)
            tui.draw_split_view = mock.MagicMock()
            tui._force_full_redraw = True
            fake = FakeScreen()
            with mock.patch.object(curses, "ACS_HLINE", "-", create=True):
                tui.draw(fake)
            self.assertIn(("clearok", True), fake.calls)
            self.assertIn(("clear",), fake.calls)
            self.assertNotIn(("erase",), fake.calls)
            self.assertFalse(tui._force_full_redraw)

    def test_draw_favorites_list_renders_empty_hint(self) -> None:
        import curses

        class FakeScreen:
            def __init__(self) -> None:
                self.lines: list[str] = []

            def addch(self, *_args, **_kwargs) -> None:
                return None

            def hline(self, *_args, **_kwargs) -> None:
                return None

            def vline(self, *_args, **_kwargs) -> None:
                return None

            def addnstr(self, _y: int, _x: int, text: str, *_args) -> None:
                self.lines.append(text)

        with tempfile.TemporaryDirectory() as temp_dir:
            store = cli.HistoryStore(path=f"{temp_dir}/history.json")
            tui = cli.BilibiliTUI(cli.BilibiliClient(), store)
            fake = FakeScreen()
            with mock.patch.object(curses, "ACS_HLINE", "-", create=True), \
                 mock.patch.object(curses, "ACS_VLINE", "|", create=True), \
                 mock.patch.object(curses, "ACS_ULCORNER", "+", create=True), \
                 mock.patch.object(curses, "ACS_URCORNER", "+", create=True), \
                 mock.patch.object(curses, "ACS_LLCORNER", "+", create=True), \
                 mock.patch.object(curses, "ACS_LRCORNER", "+", create=True):
                tui.draw_favorites_list(fake, 0, 0, 10, 42)
            rendered = " ".join(fake.lines)
            self.assertIn("收藏夹还是空的", rendered)
            self.assertIn("按 f", rendered)

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
        import curses

        class FakeWindow:
            def __init__(self) -> None:
                self.lines: list[str] = []

            def derwin(self, *args, **kwargs) -> "FakeWindow":
                return self

            def box(self) -> None:
                return None

            def addch(self, *_args, **_kwargs) -> None:
                return None

            def hline(self, *_args, **_kwargs) -> None:
                return None

            def vline(self, *_args, **_kwargs) -> None:
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
            with mock.patch.object(curses, "ACS_HLINE", "-", create=True), \
                 mock.patch.object(curses, "ACS_VLINE", "|", create=True), \
                 mock.patch.object(curses, "ACS_ULCORNER", "+", create=True), \
                 mock.patch.object(curses, "ACS_URCORNER", "+", create=True), \
                 mock.patch.object(curses, "ACS_LLCORNER", "+", create=True), \
                 mock.patch.object(curses, "ACS_LRCORNER", "+", create=True):
                tui.draw_comments_panel(fake, 0, 0, 8, 42)
            rendered = " ".join(fake.lines)
            self.assertIn("评论加载失败", rendered)
            self.assertIn("浏览器", rendered)

    def test_draw_comments_panel_renders_empty_loaded_state(self) -> None:
        import curses

        class FakeWindow:
            def __init__(self) -> None:
                self.lines: list[str] = []

            def derwin(self, *args, **kwargs) -> "FakeWindow":
                return self

            def box(self) -> None:
                return None

            def addch(self, *_args, **_kwargs) -> None:
                return None

            def hline(self, *_args, **_kwargs) -> None:
                return None

            def vline(self, *_args, **_kwargs) -> None:
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
            with mock.patch.object(curses, "ACS_HLINE", "-", create=True), \
                 mock.patch.object(curses, "ACS_VLINE", "|", create=True), \
                 mock.patch.object(curses, "ACS_ULCORNER", "+", create=True), \
                 mock.patch.object(curses, "ACS_URCORNER", "+", create=True), \
                 mock.patch.object(curses, "ACS_LLCORNER", "+", create=True), \
                 mock.patch.object(curses, "ACS_LRCORNER", "+", create=True):
                tui.draw_comments_panel(fake, 0, 0, 8, 42)
            rendered = " ".join(fake.lines)
            self.assertIn("暂无可显示热评", rendered)


if __name__ == "__main__":
    unittest.main()
