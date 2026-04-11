from __future__ import annotations

from dataclasses import dataclass

from ..bilibili_cli import HOME_CHANNELS

DEFAULT_SEARCH_PLACEHOLDER = "按 / 或 s 搜索，支持中文实时输入"
DEFAULT_STATUS_TEXT = "Textual 阶段 1 骨架已启动；当前保留原键位语义与页面结构。"
DEFAULT_AUDIO_STATUS = "音频控制栏已就位；阶段 2 将复用现有 audio 播放链路。"

HELP_LINES = [
    "↑/↓ / j/k 移动", "Enter 详情", "Esc / b 返回", "/ / s 搜索", "Tab / Shift+Tab 切换分区",
    "1-9 / 0 直选分区", "l 最近搜索", "d 默认搜索词", "h 首页", "v 历史", "m 收藏夹",
    "f 收藏", "a 播放/暂停", "x 停止", "n / p 翻页", "PgUp / PgDn 详情滚动",
    "o 浏览器打开", "c 评论", "r 刷新", "? 帮助", "q 退出",
]


@dataclass(slots=True, frozen=True)
class ChannelSpec:
    label: str
    source: str
    rid: int | None = None


@dataclass(slots=True, frozen=True)
class VideoSummary:
    title: str
    author: str
    description: str
    duration: str
    play_label: str
    url: str
    cover_url: str | None = None


@dataclass(slots=True, frozen=True)
class CommentSummary:
    author: str
    message: str
    meta: str


def default_channels() -> list[ChannelSpec]:
    return [
        ChannelSpec(
            label=str(entry.get("label", "未命名")),
            source=str(entry.get("source", "recommend")),
            rid=entry.get("rid"),
        )
        for entry in HOME_CHANNELS
    ]


def placeholder_videos(channel_label: str) -> list[VideoSummary]:
    return [
        VideoSummary(
            title=f"{channel_label} · Textual 阶段 1 预览卡片 {index}",
            author=f"{channel_label} UP {index}",
            description="封面、评论、收藏和音频控制的真实数据将在阶段 2 接到 core 层。",
            duration=f"{index + 1}:0{index}",
            play_label=f"{index * 1234} 播放",
            url=f"https://www.bilibili.com/video/BV1xx411c7m{index}",
            cover_url=None,
        )
        for index in range(1, 7)
    ]


def placeholder_comments(video: VideoSummary | None) -> list[CommentSummary]:
    subject = video.title if video is not None else "当前视频"
    return [
        CommentSummary("热评 1", f"{subject}：评论区骨架已保留，阶段 2 会接入真实热评。", "👍 2048 · 10 分钟前"),
        CommentSummary("热评 2", "评论 View 已拆成独立 widget，方便后续复用现有 comments() 数据流。", "👍 512 · 42 分钟前"),
        CommentSummary("热评 3", "阶段 1 只做布局和交互外壳，不改当前 CLI / curses 业务逻辑。", "👍 256 · 1 小时前"),
    ]


def help_text() -> str:
    return "\n".join(HELP_LINES)
