import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

from bili_terminal import core


class ParseVideoRefTests(unittest.TestCase):
    def test_parse_bvid_from_plain_text(self) -> None:
        self.assertEqual(core.parse_video_ref("BV1xx411c7mu"), ("bvid", "BV1xx411c7mu"))

    def test_parse_bvid_from_url(self) -> None:
        self.assertEqual(
            core.parse_video_ref("https://www.bilibili.com/video/BV1xx411c7mu?p=1"),
            ("bvid", "BV1xx411c7mu"),
        )

    def test_parse_aid_from_plain_text(self) -> None:
        self.assertEqual(core.parse_video_ref("av106"), ("aid", "106"))

    def test_parse_invalid_ref_raises(self) -> None:
        with self.assertRaises(ValueError):
            core.parse_video_ref("hello")


class FormattingTests(unittest.TestCase):
    def test_channel_shortcut_index_maps_numeric_keys(self) -> None:
        self.assertEqual(core.channel_shortcut_index_from_key(ord("1"), 10), 0)
        self.assertEqual(core.channel_shortcut_index_from_key(ord("9"), 10), 8)

    def test_channel_shortcut_index_maps_zero_to_tenth_channel(self) -> None:
        self.assertEqual(core.channel_shortcut_index_from_key(ord("0"), 10), 9)

    def test_channel_shortcut_index_ignores_zero_without_tenth_channel(self) -> None:
        self.assertIsNone(core.channel_shortcut_index_from_key(ord("0"), 9))

    def test_normalize_keyword_repairs_utf8_latin1_mojibake(self) -> None:
        self.assertEqual(core.normalize_keyword("ä¸­æ"), "中文")

    def test_normalize_keyword_drops_suspicious_garbage(self) -> None:
        self.assertEqual(core.normalize_keyword("ã, æ"), "")

    def test_audio_worker_command_uses_script_path_when_not_frozen(self) -> None:
        stream = core.AudioStream(
            title="标题",
            url="https://example.com/audio.m4s",
            referer="https://www.bilibili.com/video/BV1xx411c7mu",
            user_agent="UA",
            source_kind="dash-audio",
        )
        with mock.patch.object(core.sys, "executable", "/tmp/python"), mock.patch.object(core.sys, "frozen", False, create=True):
            command = core.audio_worker_command(stream)
        self.assertEqual(command[0], "/tmp/python")
        self.assertTrue(command[1].endswith("core.py"))
        self.assertEqual(command[2:], ["audio-worker", "--url", stream.url, "--referer", stream.referer, "--user-agent", "UA", "--title", "标题"])

    def test_audio_worker_command_uses_frozen_executable_without_script_path(self) -> None:
        stream = core.AudioStream(
            title="标题",
            url="https://example.com/audio.m4s",
            referer="https://www.bilibili.com/video/BV1xx411c7mu",
            user_agent="UA",
            source_kind="dash-audio",
        )
        with mock.patch.object(core.sys, "executable", "/Applications/BiliTerminal.app/Contents/Resources/runtime/BiliTerminal"), mock.patch.object(core.sys, "frozen", True, create=True):
            command = core.audio_worker_command(stream)
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
        comments = core.comments_from_payload(
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
        self.assertEqual(core.display_width("abc"), 3)
        self.assertEqual(core.display_width("中文A"), 5)

    def test_truncate_display_respects_terminal_cell_width(self) -> None:
        self.assertEqual(core.truncate_display("原神启动测试", 8), "原神...")

    def test_wrap_display_keeps_lines_within_width(self) -> None:
        lines = core.wrap_display("哔哩哔哩终端首页", 8)
        self.assertTrue(all(core.display_width(line) <= 8 for line in lines))

    def test_normalize_duration_pads_search_style_value(self) -> None:
        self.assertEqual(core.normalize_duration("5:5"), "5:05")

    def test_item_from_payload_strips_search_highlight_markup(self) -> None:
        item = core.item_from_payload(
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
            core.build_video_url({"redirect_url": "https://www.bilibili.com/bangumi/play/ep1", "bvid": "BV1xx411c7mu"}),
            "https://www.bilibili.com/bangumi/play/ep1",
        )

    def test_build_watch_url_supports_bvid(self) -> None:
        self.assertEqual(
            core.build_watch_url("bvid", "BV1xx411c7mu"),
            "https://www.bilibili.com/video/BV1xx411c7mu",
        )

    def test_item_ref_label_prefers_bangumi_episode_when_video_ids_missing(self) -> None:
        item = core.VideoItem(
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
        self.assertEqual(core.item_ref_label(item), "ep123")

    def test_bangumi_episode_id_from_item_falls_back_to_first_ep(self) -> None:
        item = core.VideoItem(
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
        self.assertEqual(core.bangumi_episode_id_from_item(item), 789)

    def test_build_detail_lines_contains_core_metadata(self) -> None:
        lines = core.build_detail_lines(
            core.VideoItem(
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
        payload = core.item_to_history_payload(
            core.VideoItem(
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
        stream = core.extract_audio_stream(
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
        stream = core.extract_audio_stream(
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

    @mock.patch.object(core, "pid_exists", return_value=True)
    def test_save_and_load_audio_playback_state(self, _mock_exists: mock.MagicMock) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with mock.patch.dict(os.environ, {"BILITERMINAL_STATE_DIR": temp_dir}, clear=False):
                core.save_audio_playback_state(
                    core.AudioPlaybackState(pid=1234, title="标题", video_key="BV1xx411c7mu", paused=True, control_pid=5678)
                )
                state = core.load_audio_playback_state()
        self.assertIsNotNone(state)
        assert state is not None
        self.assertEqual(state.pid, 1234)
        self.assertEqual(state.video_key, "BV1xx411c7mu")
        self.assertEqual(state.backend, "process")
        self.assertTrue(state.paused)
        self.assertEqual(state.control_pid, 5678)

    @mock.patch.object(core, "pid_exists", return_value=True)
    def test_save_and_load_audio_playback_state_with_media_path(self, _mock_exists: mock.MagicMock) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            media_path = os.path.join(temp_dir, "audio.m4a")
            with open(media_path, "wb") as handle:
                handle.write(b"demo")
            with mock.patch.dict(os.environ, {"BILITERMINAL_STATE_DIR": temp_dir}, clear=False):
                core.save_audio_playback_state(
                    core.AudioPlaybackState(
                        pid=2345,
                        title="标题",
                        video_key="BV1xx411c7mu",
                        backend="macos-native",
                        paused=False,
                        control_pid=6789,
                        media_path=media_path,
                    )
                )
                state = core.load_audio_playback_state()
        self.assertIsNotNone(state)
        assert state is not None
        self.assertEqual(state.pid, 2345)
        self.assertEqual(state.backend, "macos-native")
        self.assertEqual(state.control_pid, 6789)
        self.assertEqual(state.media_path, media_path)

    @mock.patch.object(core, "clear_audio_playback_state")
    @mock.patch.object(core, "cleanup_audio_media_path")
    @mock.patch.object(core, "pid_exists", return_value=False)
    def test_load_audio_playback_state_cleans_stale_process_session(
        self,
        _mock_exists: mock.MagicMock,
        mock_cleanup: mock.MagicMock,
        mock_clear: mock.MagicMock,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            media_path = os.path.join(temp_dir, "audio.m4a")
            with mock.patch.dict(os.environ, {"BILITERMINAL_STATE_DIR": temp_dir}, clear=False):
                core.save_audio_playback_state(
                    core.AudioPlaybackState(
                        pid=2345,
                        title="标题",
                        video_key="BV1xx411c7mu",
                        backend="macos-native",
                        paused=False,
                        control_pid=6789,
                        media_path=media_path,
                    )
                )
                state = core.load_audio_playback_state()
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

    @mock.patch.object(core.BilibiliClient, "_open")
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
        items = core.BilibiliClient().search("测试")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].title, "视频A")

    @mock.patch.object(core.BilibiliClient, "_open")
    def test_api_error_raises(self, mock_open: mock.MagicMock) -> None:
        mock_open.return_value = self.make_response({"code": -352, "message": "-352"})
        with self.assertRaises(core.BilibiliAPIError):
            core.BilibiliClient().popular()

    @mock.patch.object(core.BilibiliClient, "_warmup")
    @mock.patch.object(core.BilibiliClient, "_open")
    def test_retries_after_http_412(self, mock_open: mock.MagicMock, mock_warmup: mock.MagicMock) -> None:
        error = core.urllib.error.HTTPError("https://example.com", 412, "Precondition Failed", {}, io.BytesIO(b""))
        self.addCleanup(error.close)
        mock_open.side_effect = [
            error,
            self.make_response({"code": 0, "data": {"list": []}}),
        ]
        items = core.BilibiliClient().popular()
        self.assertEqual(items, [])
        mock_warmup.assert_called_once()

    @mock.patch.object(core.BilibiliClient, "_open")
    def test_warmup_hits_homepage_before_referer(self, mock_open: mock.MagicMock) -> None:
        mock_open.return_value = self.make_response({"code": 0})
        core.BilibiliClient()._warmup("https://www.bilibili.com/video/BV1xx411c7mu")
        urls = [call.args[0].full_url for call in mock_open.call_args_list]
        self.assertEqual(urls, ["https://www.bilibili.com/", "https://www.bilibili.com/video/BV1xx411c7mu"])

    @mock.patch.object(core.BilibiliClient, "_open")
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
        items = core.BilibiliClient().recommend()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].title, "首页推荐")

    @mock.patch.object(core.BilibiliClient, "_open")
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
        self.assertEqual(core.BilibiliClient().trending_keywords(2), ["原神", "中文"])

    @mock.patch.object(core.BilibiliClient, "_open")
    def test_region_ranking_honors_day_page_and_limit(self, mock_open: mock.MagicMock) -> None:
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
        items = core.BilibiliClient().region_ranking(rid=181, day=7, page=2, page_size=1)
        request = mock_open.call_args.args[0]
        self.assertIn("rid=181", request.full_url)
        self.assertIn("day=7", request.full_url)
        self.assertEqual([item.title for item in items], ["排行榜 2"])

    @mock.patch.object(core.BilibiliClient, "_open")
    def test_bangumi_latest_reads_result_payload(self, mock_open: mock.MagicMock) -> None:
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
        items = core.BilibiliClient().bangumi(page_size=1)
        request = mock_open.call_args.args[0]
        self.assertIn("/pgc/web/timeline/v2", request.full_url)
        self.assertEqual(items[0].title, "番剧更新")
        self.assertEqual(items[0].url, "https://www.bilibili.com/bangumi/play/ep1")

    def test_audio_stream_for_bangumi_item_uses_playurl_api(self) -> None:
        client = core.BilibiliClient()
        client._request_json = mock.MagicMock(return_value={"durl": [{"url": "https://example.com/bangumi.mp4"}]})
        item = core.VideoItem(
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

    def test_audio_stream_for_bangumi_index_item_ignores_string_result_field(self) -> None:
        client = core.BilibiliClient()
        client._request_json = mock.MagicMock(
            return_value={"result": "suee", "durl": [{"url": "https://example.com/index-bangumi.mp4"}]}
        )
        item = core.VideoItem(
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

    @mock.patch.object(core.BilibiliClient, "_open")
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
        comments = core.BilibiliClient().comments(123)
        self.assertEqual(comments[0].author, "评论者")
        self.assertEqual(comments[0].message, "评论内容")

    @mock.patch.object(core.BilibiliClient, "_open")
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
        core.BilibiliClient().comments(123, bvid="BV1xx411c7mu")
        request = mock_open.call_args_list[-1].args[0]
        self.assertIn("BV1xx411c7mu", request.headers["Referer"])

    @mock.patch.object(core.BilibiliClient, "_open")
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
        comments = core.BilibiliClient().comments(123, page_size=2, bvid="BV1xx411c7mu")
        request = mock_open.call_args_list[-1].args[0]
        self.assertIn("/x/v2/reply/wbi/main?", request.full_url)
        self.assertIn("web_location=1315875", request.full_url)
        self.assertEqual([comment.author for comment in comments], ["置顶", "普通"])

    @mock.patch.object(core.BilibiliClient, "_open")
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
        comments = core.BilibiliClient().comments(123, page_size=1, bvid="BV1xx411c7mu")
        request_urls = [call.args[0].full_url for call in mock_open.call_args_list]
        self.assertEqual(request_urls.count("https://www.bilibili.com/video/BV1xx411c7mu"), 2)
        self.assertEqual(comments[0].author, "普通")

    def test_audio_stream_for_item_parses_embedded_playinfo(self) -> None:
        client = core.BilibiliClient()
        client._request_text = mock.MagicMock(
            return_value=(
                '<script>window.__playinfo__={"data":{"dash":{"audio":[{"bandwidth":96000,'
                '"baseUrl":"https://example.com/audio.m4s"}]}}}</script>'
            )
        )
        item = core.VideoItem(
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

    @mock.patch.object(core, "clear_audio_playback_state")
    @mock.patch.object(core, "pid_exists", side_effect=[True, False])
    @mock.patch.object(core, "wait_for_audio_exit")
    @mock.patch.object(core, "send_audio_signal")
    @mock.patch.object(core, "load_audio_playback_state")
    def test_stop_audio_playback_terminates_current_session(
        self,
        mock_load: mock.MagicMock,
        mock_signal: mock.MagicMock,
        _mock_wait: mock.MagicMock,
        _mock_exists: mock.MagicMock,
        mock_clear: mock.MagicMock,
    ) -> None:
        mock_load.return_value = core.AudioPlaybackState(pid=4321, title="标题", video_key="BV1xx411c7mu", paused=False)
        message = core.stop_audio_playback()
        mock_signal.assert_called_once()
        mock_clear.assert_called_once()
        self.assertIn("已停止音频", message)

    @mock.patch.object(core, "cleanup_audio_media_path")
    @mock.patch.object(core, "clear_audio_playback_state")
    @mock.patch.object(core, "pid_exists", side_effect=[True, True, False])
    @mock.patch.object(core, "wait_for_audio_exit")
    @mock.patch.object(core, "send_audio_signal")
    @mock.patch.object(core, "load_audio_playback_state")
    def test_stop_audio_playback_cleans_media_path_for_process_backend(
        self,
        mock_load: mock.MagicMock,
        mock_signal: mock.MagicMock,
        _mock_wait: mock.MagicMock,
        _mock_exists: mock.MagicMock,
        mock_clear: mock.MagicMock,
        mock_cleanup: mock.MagicMock,
    ) -> None:
        mock_load.return_value = core.AudioPlaybackState(
            pid=4321,
            title="标题",
            video_key="BV1xx411c7mu",
            backend="macos-native",
            paused=False,
            control_pid=8765,
            media_path="/tmp/audio.m4a",
        )
        message = core.stop_audio_playback()
        self.assertEqual(mock_signal.call_count, 2)
        self.assertEqual(mock_signal.call_args_list[0].args, (8765, core.signal.SIGTERM))
        self.assertEqual(mock_signal.call_args_list[1].args, (4321, core.signal.SIGTERM))
        mock_cleanup.assert_called_once_with("/tmp/audio.m4a")
        mock_clear.assert_called_once()
        self.assertIn("已停止音频", message)

    @mock.patch.object(core, "save_audio_playback_state")
    @mock.patch.object(core, "send_audio_signal")
    @mock.patch.object(core, "load_audio_playback_state")
    def test_pause_audio_playback_uses_helper_pause_signal_for_macos_native(
        self,
        mock_load: mock.MagicMock,
        mock_signal: mock.MagicMock,
        mock_save: mock.MagicMock,
    ) -> None:
        state = core.AudioPlaybackState(
            pid=4321,
            title="标题",
            video_key="BV1xx411c7mu",
            backend="macos-native",
            paused=False,
            control_pid=8765,
            media_path="/tmp/audio.m4a",
        )
        mock_load.return_value = state
        message = core.pause_audio_playback()
        mock_signal.assert_called_once_with(8765, core.signal.SIGUSR1)
        self.assertTrue(state.paused)
        mock_save.assert_called_once_with(state)
        self.assertIn("已暂停音频", message)

    @mock.patch.object(core, "save_audio_playback_state")
    @mock.patch.object(core, "send_audio_signal")
    @mock.patch.object(core, "load_audio_playback_state")
    def test_resume_audio_playback_uses_helper_resume_signal_for_macos_native(
        self,
        mock_load: mock.MagicMock,
        mock_signal: mock.MagicMock,
        mock_save: mock.MagicMock,
    ) -> None:
        state = core.AudioPlaybackState(
            pid=4321,
            title="标题",
            video_key="BV1xx411c7mu",
            backend="macos-native",
            paused=True,
            control_pid=8765,
            media_path="/tmp/audio.m4a",
        )
        mock_load.return_value = state
        message = core.resume_audio_playback()
        mock_signal.assert_called_once_with(8765, core.signal.SIGUSR2)
        self.assertFalse(state.paused)
        mock_save.assert_called_once_with(state)
        self.assertIn("已继续播放音频", message)

    @mock.patch.object(core, "cleanup_audio_media_path")
    @mock.patch.object(core, "save_audio_playback_state")
    @mock.patch.object(core, "load_audio_playback_state")
    @mock.patch.object(core, "download_audio_to_path")
    @mock.patch.object(core, "prepare_audio_temp_path", return_value="/tmp/audio.m4a")
    @mock.patch.object(core, "macos_audio_helper_path", return_value="/tmp/biliterminal-audio-helper")
    @mock.patch.object(core, "build_audio_player_command", return_value=None)
    @mock.patch.object(core.subprocess, "Popen")
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
        mock_load.return_value = core.AudioPlaybackState(pid=4321, title="标题", video_key="BV1xx411c7mu")
        result = core.run_audio_worker("https://example.com/audio.m4s", "https://www.bilibili.com/video/BV1", "UA", "标题")
        self.assertEqual(result, 0)
        mock_download.assert_called_once()
        mock_popen.assert_called_once_with(
            ["/tmp/biliterminal-audio-helper", "/tmp/audio.m4a"],
            stdout=core.subprocess.DEVNULL,
            stderr=core.subprocess.DEVNULL,
            stdin=core.subprocess.DEVNULL,
        )
        saved_state = mock_save.call_args.args[0]
        self.assertEqual(saved_state.title, "标题")
        self.assertEqual(saved_state.video_key, "BV1xx411c7mu")
        self.assertEqual(saved_state.backend, "macos-native")
        self.assertEqual(saved_state.media_path, "/tmp/audio.m4a")
        self.assertEqual(saved_state.pid, os.getpid())
        self.assertEqual(saved_state.control_pid, helper_process.pid)
        mock_cleanup.assert_called_once_with("/tmp/audio.m4a")


class CoreEntrypointTests(unittest.TestCase):
    def test_core_only_exposes_internal_audio_worker_parser(self) -> None:
        args = core.build_audio_worker_parser().parse_args(
            [
                "audio-worker",
                "--url",
                "https://example.com/audio.m4s",
                "--referer",
                "https://www.bilibili.com/video/BV1xx411c7mu",
                "--user-agent",
                "UA",
                "--title",
                "标题",
            ]
        )
        self.assertEqual(args.command, "audio-worker")
        self.assertEqual(args.url, "https://example.com/audio.m4s")

    def test_core_parser_rejects_removed_user_commands(self) -> None:
        with mock.patch("sys.stderr", new=io.StringIO()):
            with self.assertRaises(SystemExit):
                core.build_audio_worker_parser().parse_args(["recommend"])

    def test_removed_cli_and_tui_are_not_exported(self) -> None:
        self.assertFalse(hasattr(core, "BilibiliCLI"))
        self.assertFalse(hasattr(core, "BilibiliTUI"))
        self.assertFalse(hasattr(core, "build_parser"))
        self.assertFalse(hasattr(core, "run_tui"))

    @mock.patch.object(core, "run_audio_worker")
    def test_run_audio_worker_command_dispatches_hidden_worker(self, mock_worker: mock.MagicMock) -> None:
        mock_worker.return_value = 0
        args = core.build_audio_worker_parser().parse_args(
            [
                "audio-worker",
                "--url",
                "https://example.com/audio.m4s",
                "--referer",
                "https://www.bilibili.com/video/BV1xx411c7mu",
                "--user-agent",
                "UA",
                "--title",
                "标题",
            ]
        )
        self.assertEqual(core.run_audio_worker_command(args), 0)
        mock_worker.assert_called_once_with(
            "https://example.com/audio.m4s",
            "https://www.bilibili.com/video/BV1xx411c7mu",
            "UA",
            "标题",
        )


class HistoryStoreTests(unittest.TestCase):
    def make_item(self, title: str = "标题", bvid: str = "BV1xx411c7mu") -> core.VideoItem:
        return core.VideoItem(
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
            store = core.HistoryStore(path=path)
            store.add_keyword("原神")
            store.add_video(self.make_item())

            reloaded = core.HistoryStore(path=path)
            self.assertEqual(reloaded.get_recent_keywords(1), ["原神"])
            self.assertEqual(reloaded.get_recent_videos(1)[0].bvid, "BV1xx411c7mu")

    def test_history_store_deduplicates_keywords(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = core.HistoryStore(path=f"{temp_dir}/history.json")
            store.add_keyword("原神")
            store.add_keyword("原神")
            self.assertEqual(store.get_recent_keywords(5), ["原神"])

    def test_history_store_repairs_mojibake_keywords_on_load(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = f"{temp_dir}/history.json"
            with open(path, "w", encoding="utf-8") as handle:
                json.dump({"recent_keywords": ["ä¸­æ", "ã, æ", "原神"], "recent_videos": []}, handle, ensure_ascii=False)
            store = core.HistoryStore(path=path)
            self.assertEqual(store.get_recent_keywords(5), ["中文", "原神"])

    def test_default_history_path_uses_explicit_state_dir_env(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with mock.patch.dict(os.environ, {"BILITERMINAL_STATE_DIR": temp_dir}, clear=False):
                self.assertEqual(
                    core.default_history_path(),
                    os.path.join(temp_dir, "biliterminal-history.json"),
                )

    def test_default_history_path_uses_home_dir_env(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with mock.patch.dict(os.environ, {"BILITERMINAL_HOME": temp_dir}, clear=False):
                self.assertEqual(
                    core.default_history_path(),
                    os.path.join(temp_dir, "state", "biliterminal-history.json"),
                )

    def test_history_store_uses_dynamic_default_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with mock.patch.dict(os.environ, {"BILITERMINAL_HOME": temp_dir}, clear=False):
                store = core.HistoryStore()
                self.assertEqual(
                    store.path,
                    os.path.join(temp_dir, "state", "biliterminal-history.json"),
                )

    def test_history_store_persists_favorites(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = f"{temp_dir}/history.json"
            store = core.HistoryStore(path=path)
            store.add_favorite(self.make_item("收藏视频"))

            reloaded = core.HistoryStore(path=path)
            self.assertEqual(reloaded.get_favorite_videos(1)[0].title, "收藏视频")

    def test_history_store_persists_watch_later_videos(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = f"{temp_dir}/history.json"
            store = core.HistoryStore(path=path)
            store.add_watch_later(self.make_item("稍后看视频"))

            reloaded = core.HistoryStore(path=path)
            self.assertEqual(reloaded.get_watch_later_videos(1)[0].title, "稍后看视频")

    def test_history_store_loads_missing_watch_later_key_backward_compatibly(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = f"{temp_dir}/history.json"
            with open(path, "w", encoding="utf-8") as handle:
                json.dump({"recent_keywords": [], "recent_videos": [], "favorite_videos": []}, handle)

            store = core.HistoryStore(path=path)
            self.assertEqual(store.get_watch_later_videos(), [])

    def test_history_store_deduplicates_and_moves_watch_later_to_front(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = core.HistoryStore(path=f"{temp_dir}/history.json")
            first = self.make_item("一号", "BV1xx411c7m1")
            second = self.make_item("二号", "BV1xx411c7m2")
            store.add_watch_later(first)
            store.add_watch_later(second)
            store.add_watch_later(first)

            watch_later = store.get_watch_later_videos()
            self.assertEqual([item.title for item in watch_later], ["一号", "二号"])

    def test_history_store_remove_watch_later_only_affects_queue(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = core.HistoryStore(path=f"{temp_dir}/history.json")
            item = self.make_item("目标")
            store.add_watch_later(item)
            store.add_favorite(item)

            self.assertTrue(store.remove_watch_later(item))
            self.assertEqual(store.get_watch_later_videos(), [])
            self.assertEqual(store.get_favorite_videos(1)[0].title, "目标")

    def test_history_store_watch_later_uses_independent_cap(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = core.HistoryStore(path=f"{temp_dir}/history.json", max_favorites=1, max_watch_later=2)
            store.add_watch_later(self.make_item("一号", "BV1xx411c7m1"))
            store.add_watch_later(self.make_item("二号", "BV1xx411c7m2"))
            store.add_watch_later(self.make_item("三号", "BV1xx411c7m3"))

            self.assertEqual([item.title for item in store.get_watch_later_videos()], ["三号", "二号"])
            self.assertEqual(store.max_favorites, 1)
            self.assertEqual(store.max_watch_later, 2)

    def test_history_store_add_video_and_favorite_do_not_auto_populate_watch_later(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = core.HistoryStore(path=f"{temp_dir}/history.json")
            item = self.make_item("目标")
            store.add_video(item)
            store.add_favorite(item)

            self.assertEqual(store.get_watch_later_videos(), [])

    def test_history_store_toggle_watch_later(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = core.HistoryStore(path=f"{temp_dir}/history.json")
            item = self.make_item("稍后看")
            self.assertTrue(store.toggle_watch_later(item))
            self.assertTrue(store.is_watch_later(item))
            self.assertFalse(store.toggle_watch_later(item))
            self.assertFalse(store.is_watch_later(item))

    def test_history_store_remove_favorite(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = core.HistoryStore(path=f"{temp_dir}/history.json")
            item = self.make_item("收藏视频")
            store.add_favorite(item)
            self.assertTrue(store.remove_favorite(item))
            self.assertEqual(store.get_favorite_videos(), [])

    def test_history_store_toggle_favorite(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = core.HistoryStore(path=f"{temp_dir}/history.json")
            item = self.make_item("收藏视频")
            self.assertTrue(store.toggle_favorite(item))
            self.assertTrue(store.is_favorite(item))
            self.assertFalse(store.toggle_favorite(item))
            self.assertFalse(store.is_favorite(item))



if __name__ == "__main__":
    unittest.main()
