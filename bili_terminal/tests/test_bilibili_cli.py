import io
import json
import os
import sys
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
    def test_channel_shortcut_index_maps_numeric_keys(self) -> None:
        self.assertEqual(cli.channel_shortcut_index_from_key(ord("1"), 10), 0)
        self.assertEqual(cli.channel_shortcut_index_from_key(ord("9"), 10), 8)

    def test_channel_shortcut_index_maps_zero_to_tenth_channel(self) -> None:
        self.assertEqual(cli.channel_shortcut_index_from_key(ord("0"), 10), 9)

    def test_channel_shortcut_index_ignores_zero_without_tenth_channel(self) -> None:
        self.assertIsNone(cli.channel_shortcut_index_from_key(ord("0"), 9))

    def test_normalize_keyword_repairs_utf8_latin1_mojibake(self) -> None:
        self.assertEqual(cli.normalize_keyword("ä¸­æ"), "中文")

    def test_normalize_keyword_drops_suspicious_garbage(self) -> None:
        self.assertEqual(cli.normalize_keyword("ã, æ"), "")

    def test_audio_worker_command_uses_module_entrypoint_when_not_frozen(self) -> None:
        stream = cli.AudioStream(
            title="标题",
            url="https://example.com/audio.m4s",
            referer="https://www.bilibili.com/video/BV1xx411c7mu",
            user_agent="UA",
            source_kind="dash-audio",
        )
        with (
            mock.patch.object(cli.sys, "executable", "/tmp/python"),
            mock.patch.object(cli.sys, "frozen", False, create=True),
        ):
            command = cli.audio_worker_command(stream)
        self.assertEqual(
            command,
            [
                "/tmp/python",
                "-m",
                "bili_terminal",
                "audio-worker",
                "--url",
                stream.url,
                "--referer",
                stream.referer,
                "--user-agent",
                "UA",
                "--title",
                "标题",
            ],
        )

    def test_audio_worker_command_uses_frozen_executable_without_script_path(
        self,
    ) -> None:
        stream = cli.AudioStream(
            title="标题",
            url="https://example.com/audio.m4s",
            referer="https://www.bilibili.com/video/BV1xx411c7mu",
            user_agent="UA",
            source_kind="dash-audio",
        )
        with (
            mock.patch.object(
                cli.sys,
                "executable",
                "/Applications/BiliTerminal.app/Contents/Resources/runtime/BiliTerminal",
            ),
            mock.patch.object(cli.sys, "frozen", True, create=True),
        ):
            command = cli.audio_worker_command(stream)
        self.assertEqual(
            command,
            [
                "/Applications/BiliTerminal.app/Contents/Resources/runtime/BiliTerminal",
                "audio-worker",
                "--url",
                stream.url,
                "--referer",
                stream.referer,
                "--user-agent",
                "UA",
                "--title",
                "标题",
            ],
        )

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
            cli.build_video_url(
                {
                    "redirect_url": "https://www.bilibili.com/bangumi/play/ep1",
                    "bvid": "BV1xx411c7mu",
                }
            ),
            "https://www.bilibili.com/bangumi/play/ep1",
        )

    def test_build_watch_url_supports_bvid(self) -> None:
        self.assertEqual(
            cli.build_watch_url("bvid", "BV1xx411c7mu"),
            "https://www.bilibili.com/video/BV1xx411c7mu",
        )

    def test_item_ref_label_prefers_bangumi_episode_when_video_ids_missing(
        self,
    ) -> None:
        item = cli.VideoItem(
            title="番剧",
            author="官方",
            bvid=None,
            aid=None,
            duration="24:00",
            play=1,
            danmaku=2,
            like=3,
            favorite=4,
            pubdate=1710000000,
            description="",
            url="https://www.bilibili.com/bangumi/play/ep123",
            raw={"episode_id": 123, "season_id": 456},
        )
        self.assertEqual(cli.item_ref_label(item), "ep123")

    def test_bangumi_episode_id_from_item_falls_back_to_first_ep(self) -> None:
        item = cli.VideoItem(
            title="番剧",
            author="官方",
            bvid=None,
            aid=None,
            duration="24:00",
            play=1,
            danmaku=2,
            like=3,
            favorite=4,
            pubdate=1710000000,
            description="",
            url="https://www.bilibili.com/bangumi/play/ss456",
            raw={"first_ep": {"ep_id": 789}},
        )
        self.assertEqual(cli.bangumi_episode_id_from_item(item), 789)

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
                            {
                                "id": 30216,
                                "bandwidth": 64000,
                                "baseUrl": "https://example.com/low.m4s",
                            },
                            {
                                "id": 30280,
                                "bandwidth": 192000,
                                "baseUrl": "https://example.com/high.m4s",
                            },
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

    @mock.patch.object(cli, "pid_exists", return_value=True)
    def test_save_and_load_audio_playback_state(
        self, _mock_exists: mock.MagicMock
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with mock.patch.dict(
                os.environ, {"BILITERMINAL_STATE_DIR": temp_dir}, clear=False
            ):
                cli.save_audio_playback_state(
                    cli.AudioPlaybackState(
                        pid=1234,
                        title="标题",
                        video_key="BV1xx411c7mu",
                        paused=True,
                        control_pid=5678,
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

    @mock.patch.object(cli, "pid_exists", return_value=True)
    def test_save_and_load_audio_playback_state_with_media_path(
        self, _mock_exists: mock.MagicMock
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            media_path = os.path.join(temp_dir, "audio.m4a")
            with open(media_path, "wb") as handle:
                handle.write(b"demo")
            with mock.patch.dict(
                os.environ, {"BILITERMINAL_STATE_DIR": temp_dir}, clear=False
            ):
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

    @mock.patch.object(cli, "clear_audio_playback_state")
    @mock.patch.object(cli, "cleanup_audio_media_path")
    @mock.patch.object(cli, "pid_exists", return_value=False)
    def test_load_audio_playback_state_cleans_stale_process_session(
        self,
        _mock_exists: mock.MagicMock,
        mock_cleanup: mock.MagicMock,
        mock_clear: mock.MagicMock,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            media_path = os.path.join(temp_dir, "audio.m4a")
            with mock.patch.dict(
                os.environ, {"BILITERMINAL_STATE_DIR": temp_dir}, clear=False
            ):
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
                        {
                            "type": "video",
                            "title": "视频A",
                            "author": "UP1",
                            "bvid": "BV1xx411c7mu",
                        },
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
    def test_retries_after_http_412(
        self, mock_open: mock.MagicMock, mock_warmup: mock.MagicMock
    ) -> None:
        error = cli.urllib.error.HTTPError(
            "https://example.com", 412, "Precondition Failed", {}, io.BytesIO(b"")
        )
        self.addCleanup(error.close)
        mock_open.side_effect = [
            error,
            self.make_response({"code": 0, "data": {"list": []}}),
        ]
        items = cli.BilibiliClient().popular()
        self.assertEqual(items, [])
        mock_warmup.assert_called_once()

    @mock.patch.object(cli.BilibiliClient, "_open")
    def test_warmup_hits_homepage_before_referer(
        self, mock_open: mock.MagicMock
    ) -> None:
        mock_open.return_value = self.make_response({"code": 0})
        cli.BilibiliClient()._warmup("https://www.bilibili.com/video/BV1xx411c7mu")
        urls = [call.args[0].full_url for call in mock_open.call_args_list]
        self.assertEqual(
            urls,
            [
                "https://www.bilibili.com/",
                "https://www.bilibili.com/video/BV1xx411c7mu",
            ],
        )

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
                            "stat": {
                                "view": 10,
                                "danmaku": 2,
                                "like": 3,
                                "favorite": 4,
                            },
                        }
                    ]
                },
            }
        )
        items = cli.BilibiliClient().recommend()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].title, "首页推荐")

    @mock.patch.object(cli.BilibiliClient, "_open")
    def test_trending_keywords_extracts_display_words(
        self, mock_open: mock.MagicMock
    ) -> None:
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
    def test_region_ranking_honors_day_page_and_limit(
        self, mock_open: mock.MagicMock
    ) -> None:
        mock_open.return_value = self.make_response(
            {
                "code": 0,
                "data": [
                    {"title": "排行榜 1", "author": "UP1", "bvid": "BV1xx411c7m1"},
                    {"title": "排行榜 2", "author": "UP2", "bvid": "BV1xx411c7m2"},
                    {"title": "排行榜 3", "author": "UP3", "bvid": "BV1xx411c7m3"},
                ],
            }
        )
        items = cli.BilibiliClient().region_ranking(rid=181, day=7, page=2, page_size=1)
        request = mock_open.call_args.args[0]
        self.assertIn("rid=181", request.full_url)
        self.assertIn("day=7", request.full_url)
        self.assertEqual([item.title for item in items], ["排行榜 2"])

    @mock.patch.object(cli.BilibiliClient, "_open")
    def test_bangumi_latest_reads_result_payload(
        self, mock_open: mock.MagicMock
    ) -> None:
        mock_open.return_value = self.make_response(
            {
                "code": 0,
                "result": {
                    "latest": [
                        {
                            "title": "番剧更新",
                            "episode_id": 1,
                            "pub_index": "第1话",
                            "pub_ts": 1710000000,
                        }
                    ],
                    "timeline": [],
                },
            }
        )
        items = cli.BilibiliClient().bangumi(page_size=1)
        request = mock_open.call_args.args[0]
        self.assertIn("/pgc/web/timeline/v2", request.full_url)
        self.assertEqual(items[0].title, "番剧更新")
        self.assertEqual(items[0].url, "https://www.bilibili.com/bangumi/play/ep1")

    def test_audio_stream_for_bangumi_item_uses_playurl_api(self) -> None:
        client = cli.BilibiliClient()
        client._request_json = mock.MagicMock(
            return_value={"durl": [{"url": "https://example.com/bangumi.mp4"}]}
        )
        item = cli.VideoItem(
            title="番剧更新",
            author="官方",
            bvid=None,
            aid=None,
            duration="24:00",
            play=1,
            danmaku=2,
            like=3,
            favorite=4,
            pubdate=1710000000,
            description="",
            url="https://www.bilibili.com/bangumi/play/ep123",
            raw={"episode_id": 123},
        )
        stream = client.audio_stream_for_item(item)
        client._request_json.assert_called_once_with(
            "https://api.bilibili.com/pgc/player/web/playurl",
            {"ep_id": 123, "fnval": 4048, "fourk": 1},
            "https://www.bilibili.com/bangumi/play/ep123",
        )
        self.assertEqual(stream.url, "https://example.com/bangumi.mp4")
        self.assertEqual(stream.source_kind, "media")

    def test_audio_stream_for_bangumi_index_item_ignores_string_result_field(
        self,
    ) -> None:
        client = cli.BilibiliClient()
        client._request_json = mock.MagicMock(
            return_value={
                "result": "suee",
                "durl": [{"url": "https://example.com/index-bangumi.mp4"}],
            }
        )
        item = cli.VideoItem(
            title="番剧索引",
            author="官方",
            bvid=None,
            aid=None,
            duration="24:00",
            play=1,
            danmaku=2,
            like=3,
            favorite=4,
            pubdate=1710000000,
            description="",
            url="https://www.bilibili.com/bangumi/play/ss456",
            raw={"first_ep": {"ep_id": 789}},
        )
        stream = client.audio_stream_for_item(item)
        self.assertEqual(stream.url, "https://example.com/index-bangumi.mp4")
        self.assertEqual(stream.source_kind, "media")

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
    def test_comments_prefers_bvid_referer_when_present(
        self, mock_open: mock.MagicMock
    ) -> None:
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
    def test_comments_with_bvid_uses_wbi_main_and_merges_top_replies(
        self, mock_open: mock.MagicMock
    ) -> None:
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
    def test_comments_with_bvid_refreshes_cached_wbi_keys_after_permission_error(
        self, mock_open: mock.MagicMock
    ) -> None:
        mock_open.side_effect = [
            self.make_text_response(
                (
                    '<script>window.__INITIAL_STATE__={"abtest":{"comment_version_hash":"hash123"},'
                    '"defaultWbiKey":{"wbiImgKey":"img","wbiSubKey":"sub"}};(function(){})</script>'
                )
            ),
            self.make_text_response(
                'encWbiKeys:{wbiImgKey:"oldimg",wbiSubKey:"oldsub"}'
            ),
            self.make_response({"code": -403, "message": "访问权限不足"}),
            self.make_text_response(
                (
                    '<script>window.__INITIAL_STATE__={"abtest":{"comment_version_hash":"hash456"},'
                    '"defaultWbiKey":{"wbiImgKey":"img","wbiSubKey":"sub"}};(function(){})</script>'
                )
            ),
            self.make_text_response(
                'encWbiKeys:{wbiImgKey:"newimg",wbiSubKey:"newsub"}'
            ),
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
        self.assertEqual(
            request_urls.count("https://www.bilibili.com/video/BV1xx411c7mu"), 2
        )
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

    @mock.patch.object(cli, "clear_audio_playback_state")
    @mock.patch.object(cli, "pid_exists", side_effect=[True, False])
    @mock.patch.object(cli, "wait_for_audio_exit")
    @mock.patch.object(cli.platform_audio, "terminate_process")
    @mock.patch.object(cli, "load_audio_playback_state")
    def test_stop_audio_playback_terminates_current_session(
        self,
        mock_load: mock.MagicMock,
        mock_terminate: mock.MagicMock,
        _mock_wait: mock.MagicMock,
        _mock_exists: mock.MagicMock,
        mock_clear: mock.MagicMock,
    ) -> None:
        mock_load.return_value = cli.AudioPlaybackState(
            pid=4321, title="标题", video_key="BV1xx411c7mu", paused=False
        )
        message = cli.stop_audio_playback()
        mock_terminate.assert_called_once_with(4321)
        mock_clear.assert_called_once()
        self.assertIn("已停止音频", message)

    @mock.patch.object(cli, "cleanup_audio_media_path")
    @mock.patch.object(cli, "clear_audio_playback_state")
    @mock.patch.object(cli, "pid_exists", side_effect=[True, True, False])
    @mock.patch.object(cli, "wait_for_audio_exit")
    @mock.patch.object(cli.platform_audio, "terminate_process")
    @mock.patch.object(cli, "load_audio_playback_state")
    def test_stop_audio_playback_cleans_media_path_for_process_backend(
        self,
        mock_load: mock.MagicMock,
        mock_terminate: mock.MagicMock,
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
        self.assertEqual(mock_terminate.call_count, 2)
        mock_terminate.assert_any_call(8765)
        mock_terminate.assert_any_call(4321)
        mock_cleanup.assert_called_once_with("/tmp/audio.m4a")
        mock_clear.assert_called_once()
        self.assertIn("已停止音频", message)

    @mock.patch.object(cli, "save_audio_playback_state")
    @mock.patch.object(cli, "send_audio_signal")
    @mock.patch.object(cli, "load_audio_playback_state")
    def test_pause_audio_playback_uses_helper_pause_signal_for_macos_native(
        self,
        mock_load: mock.MagicMock,
        mock_signal: mock.MagicMock,
        mock_save: mock.MagicMock,
    ) -> None:
        sigusr1 = getattr(cli.signal, "SIGUSR1", None)
        if sigusr1 is None:
            self.skipTest("SIGUSR1 not available on this platform")
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
        mock_signal.assert_called_once_with(8765, sigusr1)
        self.assertTrue(state.paused)
        mock_save.assert_called_once_with(state)
        self.assertIn("已暂停音频", message)

    @mock.patch.object(cli, "save_audio_playback_state")
    @mock.patch.object(cli, "send_audio_signal")
    @mock.patch.object(cli, "load_audio_playback_state")
    def test_resume_audio_playback_uses_helper_resume_signal_for_macos_native(
        self,
        mock_load: mock.MagicMock,
        mock_signal: mock.MagicMock,
        mock_save: mock.MagicMock,
    ) -> None:
        sigusr2 = getattr(cli.signal, "SIGUSR2", None)
        if sigusr2 is None:
            self.skipTest("SIGUSR2 not available on this platform")
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
        mock_signal.assert_called_once_with(8765, sigusr2)
        self.assertFalse(state.paused)
        mock_save.assert_called_once_with(state)
        self.assertIn("已继续播放音频", message)

    @mock.patch.object(cli, "cleanup_audio_media_path")
    @mock.patch.object(cli, "save_audio_playback_state")
    @mock.patch.object(cli, "load_audio_playback_state")
    @mock.patch.object(cli, "download_audio_to_path")
    @mock.patch.object(cli, "prepare_audio_temp_path", return_value="/tmp/audio.m4a")
    @mock.patch.object(
        cli, "macos_audio_helper_path", return_value="/tmp/biliterminal-audio-helper"
    )
    @mock.patch.object(cli, "build_audio_player_command", return_value=None)
    @mock.patch.object(cli.subprocess, "Popen")
    def test_run_audio_worker_switches_to_macos_native_helper(
        self,
        mock_popen: mock.MagicMock,
        _mock_build_command: mock.MagicMock,
        _mock_helper_path: mock.MagicMock,
        _mock_prepare_path: mock.MagicMock,
        mock_download: mock.MagicMock,
        mock_load: mock.MagicMock,
        mock_save: mock.MagicMock,
        mock_cleanup: mock.MagicMock,
    ) -> None:
        helper_process = mock.MagicMock()
        helper_process.pid = 9988
        helper_process.wait.return_value = 0
        mock_popen.return_value = helper_process
        mock_load.return_value = cli.AudioPlaybackState(
            pid=4321, title="标题", video_key="BV1xx411c7mu"
        )
        result = cli.run_audio_worker(
            "https://example.com/audio.m4s",
            "https://www.bilibili.com/video/BV1",
            "UA",
            "标题",
        )
        self.assertEqual(result, 0)
        mock_download.assert_called_once()
        mock_popen.assert_called_once_with(
            ["/tmp/biliterminal-audio-helper", "/tmp/audio.m4a"],
            stdout=cli.subprocess.DEVNULL,
            stderr=cli.subprocess.DEVNULL,
            stdin=cli.subprocess.DEVNULL,
        )
        saved_state = mock_save.call_args.args[0]
        self.assertEqual(saved_state.title, "标题")
        self.assertEqual(saved_state.video_key, "BV1xx411c7mu")
        self.assertEqual(saved_state.backend, "macos-native")
        self.assertEqual(saved_state.media_path, "/tmp/audio.m4a")
        self.assertEqual(saved_state.pid, os.getpid())
        self.assertEqual(saved_state.control_pid, helper_process.pid)
        mock_cleanup.assert_called_once_with("/tmp/audio.m4a")


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

    def test_parser_supports_rank_command(self) -> None:
        args = cli.build_parser().parse_args(
            ["rank", "动画", "--day", "7", "--page", "2", "--limit", "3"]
        )
        self.assertEqual(args.command, "rank")
        self.assertEqual(args.region, "动画")
        self.assertEqual(args.day, 7)
        self.assertEqual(args.page, 2)
        self.assertEqual(args.limit, 3)

    def test_parser_supports_ranking_alias_with_rid(self) -> None:
        args = cli.build_parser().parse_args(
            ["ranking", "--rid", "181", "--day", "7", "--limit", "4"]
        )
        self.assertEqual(args.command, "ranking")
        self.assertEqual(args.rid, 181)
        self.assertEqual(args.day, 7)
        self.assertEqual(args.limit, 4)

    def test_parser_supports_bangumi_command_with_index_filters(self) -> None:
        args = cli.build_parser().parse_args(
            [
                "bangumi",
                "番剧",
                "--index",
                "--area",
                "大陆",
                "--page",
                "2",
                "--limit",
                "4",
            ]
        )
        self.assertEqual(args.command, "bangumi")
        self.assertEqual(args.category, "番剧")
        self.assertTrue(args.index)
        self.assertEqual(args.area, "大陆")
        self.assertEqual(args.page, 2)
        self.assertEqual(args.limit, 4)

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

    @mock.patch.object(cli, "play_audio_for_item")
    def test_do_audio_by_index_uses_last_results(
        self, mock_play_audio: mock.MagicMock
    ) -> None:
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

    @mock.patch.object(cli, "stop_audio_playback")
    def test_do_audio_stop_uses_audio_control(
        self, mock_stop_audio: mock.MagicMock
    ) -> None:
        mock_stop_audio.return_value = "已停止音频: 标题"
        shell = cli.BilibiliCLI(cli.BilibiliClient(), self.make_store())
        with mock.patch("sys.stdout", new=io.StringIO()) as stdout:
            shell.do_audio("stop")
        mock_stop_audio.assert_called_once()
        self.assertIn("已停止音频", stdout.getvalue())

    def test_rank_command_updates_last_items(self) -> None:
        item = cli.VideoItem(
            title="动画排行",
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
        client = mock.MagicMock(spec=cli.BilibiliClient)
        client.region_ranking.return_value = [item]
        shell = cli.BilibiliCLI(client, self.make_store())
        with mock.patch("sys.stdout", new=io.StringIO()) as stdout:
            shell.onecmd("rank 动画 --day 7 --page 2 --limit 3")
        client.region_ranking.assert_called_once()
        self.assertEqual(shell.last_items, [item])
        self.assertIn("动画排行", stdout.getvalue())

    def test_bangumi_command_updates_last_items(self) -> None:
        item = cli.VideoItem(
            title="番剧更新",
            author="番剧官方",
            bvid=None,
            aid=None,
            duration="24:00",
            play=1,
            danmaku=2,
            like=3,
            favorite=4,
            pubdate=1710000000,
            description="",
            url="https://www.bilibili.com/bangumi/play/ep1",
            raw={},
        )
        client = mock.MagicMock(spec=cli.BilibiliClient)
        client.bangumi.return_value = [item]
        shell = cli.BilibiliCLI(client, self.make_store())
        with mock.patch("sys.stdout", new=io.StringIO()) as stdout:
            shell.onecmd("bangumi 番剧 --index --area 大陆 --page 2 --limit 3")
        client.bangumi.assert_called_once()
        self.assertEqual(shell.last_items, [item])
        self.assertIn("番剧更新", stdout.getvalue())

    def test_do_video_by_index_uses_last_bangumi_item_without_lookup(self) -> None:
        item = cli.VideoItem(
            title="番剧更新",
            author="番剧官方",
            bvid=None,
            aid=None,
            duration="24:00",
            play=1,
            danmaku=2,
            like=3,
            favorite=4,
            pubdate=1710000000,
            description="简介",
            url="https://www.bilibili.com/bangumi/play/ep1",
            raw={"episode_id": 1},
        )
        client = mock.MagicMock(spec=cli.BilibiliClient)
        shell = cli.BilibiliCLI(client, self.make_store())
        shell.last_items = [item]
        with mock.patch("sys.stdout", new=io.StringIO()) as stdout:
            shell.do_video("1")
        client.video.assert_not_called()
        self.assertIn("番剧更新", stdout.getvalue())

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


class CommandDispatchTests(unittest.TestCase):
    def make_store(self) -> cli.HistoryStore:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        return cli.HistoryStore(path=f"{temp_dir.name}/history.json")

    def make_item(
        self, title: str = "标题", bvid: str = "BV1xx411c7mu"
    ) -> cli.VideoItem:
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

    @mock.patch.object(cli, "print_video_list")
    def test_run_once_rank_uses_region_ranking(
        self, mock_print_video_list: mock.MagicMock
    ) -> None:
        client = mock.MagicMock(spec=cli.BilibiliClient)
        client.region_ranking.return_value = [self.make_item("影视排行")]
        args = cli.build_parser().parse_args(
            ["rank", "--rid", "181", "--day", "7", "--page", "2", "--limit", "3"]
        )
        result = cli.run_once(args, client, self.make_store())
        self.assertEqual(result, 0)
        client.region_ranking.assert_called_once_with(
            rid=181, day=7, page_size=3, page=2
        )
        mock_print_video_list.assert_called_once()

    @mock.patch.object(cli, "print_video_list")
    def test_run_once_bangumi_uses_client_bangumi(
        self, mock_print_video_list: mock.MagicMock
    ) -> None:
        client = mock.MagicMock(spec=cli.BilibiliClient)
        client.bangumi.return_value = [self.make_item("番剧索引")]
        args = cli.build_parser().parse_args(
            [
                "bangumi",
                "番剧",
                "--index",
                "--area",
                "大陆",
                "--page",
                "2",
                "--limit",
                "4",
            ]
        )
        result = cli.run_once(args, client, self.make_store())
        self.assertEqual(result, 0)
        client.bangumi.assert_called_once()
        mock_print_video_list.assert_called_once()


class HistoryStoreTests(unittest.TestCase):
    def make_item(
        self, title: str = "标题", bvid: str = "BV1xx411c7mu"
    ) -> cli.VideoItem:
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
                json.dump(
                    {"recent_keywords": ["ä¸­æ", "ã, æ", "原神"], "recent_videos": []},
                    handle,
                    ensure_ascii=False,
                )
            store = cli.HistoryStore(path=path)
            self.assertEqual(store.get_recent_keywords(5), ["中文", "原神"])

    def test_default_history_path_uses_explicit_state_dir_env(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with mock.patch.dict(
                os.environ, {"BILITERMINAL_STATE_DIR": temp_dir}, clear=False
            ):
                self.assertEqual(
                    cli.default_history_path(),
                    os.path.join(temp_dir, "bilibili-cli-history.json"),
                )

    def test_default_history_path_uses_home_dir_env(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with mock.patch.dict(
                os.environ, {"BILITERMINAL_HOME": temp_dir}, clear=False
            ):
                self.assertEqual(
                    cli.default_history_path(),
                    os.path.join(temp_dir, "state", "bilibili-cli-history.json"),
                )

    def test_history_store_uses_dynamic_default_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with mock.patch.dict(
                os.environ, {"BILITERMINAL_HOME": temp_dir}, clear=False
            ):
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


class TUIStateTests(unittest.TestCase):
    def make_item(
        self, title: str = "标题", bvid: str = "BV1xx411c7mu"
    ) -> cli.VideoItem:
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

    def make_bangumi_item(
        self, title: str = "番剧更新", episode_id: int = 1
    ) -> cli.VideoItem:
        return cli.VideoItem(
            title=title,
            author="第1话",
            bvid=None,
            aid=None,
            duration="第1话",
            play=1,
            danmaku=0,
            like=3,
            favorite=4,
            pubdate=1710000000,
            description="简介",
            url=f"https://www.bilibili.com/bangumi/play/ep{episode_id}",
            raw={"episode_id": episode_id},
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
            self.assertIn(
                ("init_pair", 1, fake_curses.COLOR_WHITE, 13), fake_curses.calls
            )
            self.assertIn(
                ("init_pair", 4, fake_curses.COLOR_BLACK, 13), fake_curses.calls
            )
            self.assertTrue(tui.use_colors)

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

    def test_load_items_uses_bangumi_channel(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = cli.HistoryStore(path=f"{temp_dir}/history.json")
            client = cli.BilibiliClient()
            client.bangumi = mock.MagicMock(return_value=[self.make_bangumi_item()])
            client.video = mock.MagicMock()
            tui = cli.BilibiliTUI(client, store)
            tui.channel_index = len(tui.channels) - 1
            tui.load_items()
            client.bangumi.assert_called_once_with(
                category="番剧", index=False, area=None, page=1, page_size=tui.limit
            )
            client.video.assert_not_called()
            self.assertEqual(tui.items[0].title, "番剧更新")

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
            tui.current_comments = mock.MagicMock(
                return_value=[
                    cli.CommentItem(
                        author="评论者", message="内容", like=1, ctime=1710000000
                    )
                ]
            )
            tui.refresh_comments()
            tui.ensure_comments_for_selected.assert_called_once_with(force=True)
            self.assertEqual(tui.status, "已加载评论 1 条")

    def test_refresh_comments_surfaces_error_message(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = cli.HistoryStore(path=f"{temp_dir}/history.json")
            tui = cli.BilibiliTUI(cli.BilibiliClient(), store)
            tui.items = [self.make_item()]
            tui.ensure_comments_for_selected = mock.MagicMock()
            tui.current_comment_error = mock.MagicMock(
                return_value="评论接口受限，请按 o 在浏览器中查看"
            )
            tui.refresh_comments()
            tui.ensure_comments_for_selected.assert_called_once_with(force=True)
            self.assertIn("评论加载失败", tui.status)

    def test_refresh_comments_for_bangumi_item_shows_unavailable_hint(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = cli.HistoryStore(path=f"{temp_dir}/history.json")
            client = cli.BilibiliClient()
            client.video = mock.MagicMock()
            client.comments = mock.MagicMock()
            tui = cli.BilibiliTUI(client, store)
            tui.items = [self.make_bangumi_item(episode_id=3243121)]
            tui.refresh_comments()
            client.video.assert_not_called()
            client.comments.assert_not_called()
            self.assertIn("番剧条目暂不支持评论预览", tui.status)

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

    @mock.patch.object(cli, "play_audio_for_item")
    def test_play_selected_audio_updates_status(
        self, mock_play_audio: mock.MagicMock
    ) -> None:
        mock_play_audio.return_value = "已开始播放音频: 标题"
        with tempfile.TemporaryDirectory() as temp_dir:
            store = cli.HistoryStore(path=f"{temp_dir}/history.json")
            tui = cli.BilibiliTUI(cli.BilibiliClient(), store)
            tui.items = [self.make_item()]
            tui.play_selected_audio()
            mock_play_audio.assert_called_once()
            self.assertEqual(tui.status, "已开始播放音频: 标题")

    @mock.patch.object(cli, "toggle_audio_playback")
    @mock.patch.object(cli, "load_audio_playback_state")
    @mock.patch.object(cli, "play_audio_for_item")
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

    @mock.patch.object(cli, "stop_audio_playback")
    def test_stop_audio_updates_status(self, mock_stop_audio: mock.MagicMock) -> None:
        mock_stop_audio.return_value = "已停止音频: 标题"
        with tempfile.TemporaryDirectory() as temp_dir:
            store = cli.HistoryStore(path=f"{temp_dir}/history.json")
            tui = cli.BilibiliTUI(cli.BilibiliClient(), store)
            tui.stop_audio()
            mock_stop_audio.assert_called_once()
            self.assertEqual(tui.status, "已停止音频: 标题")

    def test_mode_token_uses_favorites_label(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = cli.HistoryStore(path=f"{temp_dir}/history.json")
            tui = cli.BilibiliTUI(cli.BilibiliClient(), store)
            tui.mode = "favorites"
            self.assertEqual(tui.mode_token(), "收藏夹")

    def test_draw_featured_card_compact_marks_favorite(self) -> None:
        class FakeScreen:
            def __init__(self) -> None:
                self.lines: list[str] = []

            def derwin(self, *_args, **_kwargs) -> "FakeScreen":
                return self

            def box(self) -> None:
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
            tui.draw_featured_card(fake, 0, 0, 8, 40, item, selected=False)
            rendered = " ".join(fake.lines)
            self.assertIn("★ 收藏卡片", rendered)

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

    def test_draw_favorites_list_renders_empty_hint(self) -> None:
        class FakeScreen:
            def __init__(self) -> None:
                self.lines: list[str] = []

            def addnstr(self, _y: int, _x: int, text: str, *_args) -> None:
                self.lines.append(text)

        with tempfile.TemporaryDirectory() as temp_dir:
            store = cli.HistoryStore(path=f"{temp_dir}/history.json")
            tui = cli.BilibiliTUI(cli.BilibiliClient(), store)
            fake = FakeScreen()
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
            tui.comment_errors[item.bvid or str(item.aid)] = (
                "评论接口受限，请按 o 在浏览器中查看"
            )
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

    def test_draw_comments_panel_renders_bangumi_unavailable_hint(self) -> None:
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
            tui.items = [self.make_bangumi_item(episode_id=3243121)]
            fake = FakeWindow()
            tui.draw_comments_panel(fake, 0, 0, 8, 42)
            rendered = " ".join(fake.lines)
            self.assertIn("番剧条目暂不支持评论预览", rendered)
            self.assertIn("浏览器", rendered)


if __name__ == "__main__":
    unittest.main()
