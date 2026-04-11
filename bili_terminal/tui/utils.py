from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from ..bilibili_cli import (
    BilibiliAPIError,
    COMMENT_WEB_LOCATION,
    HOME_CHANNELS,
    CommentItem,
    VideoItem,
    build_detail_lines,
    format_timestamp,
    human_count,
    is_bangumi_item,
    video_lookup_ref_from_item,
)

DEFAULT_SEARCH_PLACEHOLDER = "按 / 或 s 搜索，支持中文实时输入"
DEFAULT_STATUS_TEXT = "Textual 阶段 1 骨架已启动；当前保留原键位语义与页面结构。"
DEFAULT_AUDIO_STATUS = "音频控制栏已就位；阶段 2 将复用现有 audio 播放链路。"
DEFAULT_COMMENT_PLACEHOLDER = "评论区已预留；按 c 可加载热评，异常时会在此处直接提示。"

HELP_LINES = [
    "↑/↓ / j/k 移动",
    "Enter 详情",
    "Esc / b 返回",
    "/ / s 搜索",
    "Tab / Shift+Tab 切换分区",
    "1-9 / 0 直选分区",
    "l 最近搜索",
    "d 默认搜索词",
    "h 首页",
    "v 历史",
    "m 收藏夹",
    "f 收藏",
    "a 播放/暂停",
    "x 停止",
    "n / p 翻页",
    "PgUp / PgDn 详情滚动",
    "o 浏览器打开",
    "c 评论",
    "r 刷新",
    "? 帮助",
    "q 退出",
]


@dataclass(slots=True, frozen=True)
class ChannelSpec:
    label: str
    source: str
    rid: int | None = None
    category: str | None = None
    index_mode: bool = False
    area: str | None = None


@dataclass(slots=True, frozen=True)
class VideoSummary:
    title: str
    author: str
    description: str
    duration: str
    play_label: str
    url: str
    cover_url: str | None = None
    bvid: str | None = None
    aid: int | None = None
    favorite: bool = False
    published_label: str = "-"
    stat_line: str = ""
    ref_label: str = "-"
    item: VideoItem | None = field(default=None, repr=False, compare=False)


@dataclass(slots=True, frozen=True)
class CommentSummary:
    author: str
    message: str
    meta: str
    like: int = 0
    ctime: int | None = None


@dataclass(slots=True, frozen=True)
class FeedSnapshot:
    mode: Literal["home", "search", "history", "favorites"]
    title: str
    videos: tuple[VideoSummary, ...]
    empty_message: str
    page: int = 1
    keyword: str = ""
    channel_index: int = 0


@dataclass(slots=True, frozen=True)
class DetailSnapshot:
    video: VideoSummary | None
    lines: tuple[str, ...]
    comments: tuple[CommentSummary, ...]
    favorite: bool
    comments_error: str | None = None


@dataclass(slots=True, frozen=True)
class AudioStatus:
    now_playing: str
    state: Literal["playing", "paused", "stopped"]
    status_message: str


class TextualAdapter:
    """Small bridge that exposes existing CLI logic in Textual-friendly shapes."""

    def __init__(
        self,
        *,
        client: BilibiliClient | None = None,
        history_store: HistoryStore | None = None,
    ) -> None:
        self.client = client or BilibiliClient()
        self.history_store = history_store or HistoryStore()
        self.channels = default_channels()

    def load_home(self, *, channel_index: int = 0, page: int = 1, page_size: int = 10) -> FeedSnapshot:
        channel = self.channels[max(0, min(channel_index, len(self.channels) - 1))]
        if channel.source == "recommend":
            items = self.client.recommend(page=page, page_size=page_size)
        elif channel.source == "popular":
            items = self.client.popular(page=page, page_size=page_size)
        elif channel.source == "precious":
            items = self.client.precious(page=page, page_size=page_size)
        elif channel.source == "bangumi":
            items = self.client.bangumi(
                category=channel.category or "番剧",
                index=channel.index_mode,
                area=channel.area,
                page=page,
                page_size=page_size,
            )
        else:
            if channel.rid is None:
                raise BilibiliAPIError(f"分区 {channel.label} 缺少 rid")
            items = self.client.region_ranking(channel.rid, page=page, page_size=page_size)
        return FeedSnapshot(
            mode="home",
            title=f"{channel.label}  第 {page} 页",
            videos=tuple(self.video_summary(item) for item in items),
            empty_message=f"{channel.label} 当前没有可展示的视频。",
            page=page,
            channel_index=channel_index,
        )

    def search(self, keyword: str, *, page: int = 1, page_size: int = 10) -> FeedSnapshot:
        cleaned = normalize_keyword(keyword)
        if not cleaned:
            return FeedSnapshot(
                mode="search",
                title="搜索",
                videos=(),
                empty_message="请输入有效关键词。",
                page=page,
                keyword="",
            )
        items = self.client.search(cleaned, page=page, page_size=page_size)
        self.history_store.add_keyword(cleaned)
        return FeedSnapshot(
            mode="search",
            title=f"搜索: {cleaned}  第 {page} 页",
            videos=tuple(self.video_summary(item) for item in items),
            empty_message=f"没有找到与“{cleaned}”相关的视频。",
            page=page,
            keyword=cleaned,
        )

    def history(self, *, limit: int = 20) -> FeedSnapshot:
        items = self.history_store.get_recent_videos(limit)
        return FeedSnapshot(
            mode="history",
            title="最近浏览",
            videos=tuple(self.video_summary(item) for item in items),
            empty_message="最近还没有浏览记录。",
        )

    def favorites(self, *, limit: int | None = None) -> FeedSnapshot:
        items = self.history_store.get_favorite_videos(limit)
        return FeedSnapshot(
            mode="favorites",
            title="收藏夹",
            videos=tuple(self.video_summary(item) for item in items),
            empty_message="收藏夹还是空的。",
        )

    def detail(self, video: VideoSummary | VideoItem | None, *, width: int = 56, comment_limit: int = 4) -> DetailSnapshot:
        item = self._resolve_item(video)
        if item is None:
            return DetailSnapshot(
                video=None,
                lines=("当前没有可展示的详情。",),
                comments=(),
                favorite=False,
            )
        self.history_store.add_video(item)
        comments_error: str | None = None
        comments: tuple[CommentSummary, ...] = ()
        if item.aid is not None:
            try:
                comments = self.comments(item, page_size=comment_limit)
            except BilibiliAPIError as exc:
                comments_error = str(exc)
        lines = tuple(build_detail_lines(item, width=max(20, width)))
        return DetailSnapshot(
            video=self.video_summary(item),
            lines=lines,
            comments=comments,
            comments_error=comments_error,
            favorite=self.history_store.is_favorite(item),
        )

    def comments(self, video: VideoSummary | VideoItem | None, *, page_size: int = 4) -> tuple[CommentSummary, ...]:
        item = self._resolve_item(video)
        if item is None or item.aid is None:
            return ()
        comments = self.client.comments(item.aid, page_size=page_size, bvid=item.bvid)
        return tuple(comment_summary_from_item(comment) for comment in comments)

    def toggle_favorite(self, video: VideoSummary | VideoItem | None) -> bool:
        item = self._resolve_item(video)
        if item is None:
            raise BilibiliAPIError("当前没有可收藏的视频")
        return self.history_store.toggle_favorite(item)

    def is_favorite(self, video: VideoSummary | VideoItem | None) -> bool:
        item = self._resolve_item(video)
        return self.history_store.is_favorite(item)

    def toggle_audio(self, video: VideoSummary | VideoItem | None) -> AudioStatus:
        item = self._resolve_item(video)
        if item is None:
            return AudioStatus(now_playing="未播放", state="stopped", status_message="当前没有可播放音频的视频")
        self.history_store.add_video(item)
        message = audio_action_for_item(self.client, item)
        return self.current_audio_status(default_title=item.title, fallback_message=message)

    def stop_audio(self) -> AudioStatus:
        try:
            message = stop_audio_playback()
        except BilibiliAPIError as exc:
            return AudioStatus(now_playing="未播放", state="stopped", status_message=str(exc))
        return AudioStatus(now_playing="未播放", state="stopped", status_message=message)

    def current_audio_status(
        self,
        *,
        default_title: str = "未播放",
        fallback_message: str = DEFAULT_AUDIO_STATUS,
    ) -> AudioStatus:
        state = load_audio_playback_state()
        return audio_status_from_state(state, default_title=default_title, fallback_message=fallback_message)

    def recent_keywords(self, limit: int = 10) -> list[str]:
        return self.history_store.get_recent_keywords(limit)

    def default_search_keyword(self) -> str:
        return self.client.search_default()

    def trending_keywords(self, limit: int = 8) -> list[str]:
        return self.client.trending_keywords(limit)

    def video_summary(self, item: VideoItem) -> VideoSummary:
        return video_summary_from_item(item, history_store=self.history_store)

    def _resolve_item(self, video: VideoSummary | VideoItem | None) -> VideoItem | None:
        if video is None:
            return None
        if isinstance(video, VideoItem):
            return video
        if video.item is not None:
            return video.item
        if video.bvid or video.aid is not None:
            ref = video.bvid or f"av{video.aid}"
            return self.client.video(ref)
        return None


def default_channels() -> list[ChannelSpec]:
    return [
        ChannelSpec(
            label=str(entry.get("label", "未命名")),
            source=str(entry.get("source", "recommend")),
            rid=entry.get("rid"),
            category=entry.get("category"),
            index_mode=bool(entry.get("index")),
            area=entry.get("area"),
        )
        for entry in HOME_CHANNELS
    ]


def video_summary_from_item(item: VideoItem, *, history_store: HistoryStore | None = None) -> VideoSummary:
    return VideoSummary(
        title=item.title,
        author=item.author,
        description=item.description or "暂无简介",
        duration=item.duration,
        play_label=human_count(item.play),
        url=item.url,
        cover_url=_cover_url_from_item(item),
        bvid=item.bvid,
        aid=item.aid,
        favorite=history_store.is_favorite(item) if history_store is not None else False,
        published_label=format_timestamp(item.pubdate),
        stat_line=(
            f"播放 {human_count(item.play)} · 弹幕 {human_count(item.danmaku)} · "
            f"点赞 {human_count(item.like)} · 收藏 {human_count(item.favorite)}"
        ),
        ref_label=item_ref_label(item),
        item=item,
    )


def comment_summary_from_item(comment: CommentItem) -> CommentSummary:
    return CommentSummary(
        author=comment.author,
        message=comment.message or "暂无评论内容",
        meta=f"👍 {human_count(comment.like)} · {format_timestamp(comment.ctime)}",
        like=comment.like,
        ctime=comment.ctime,
    )


def audio_status_from_state(
    state: AudioPlaybackState | None,
    *,
    default_title: str = "未播放",
    fallback_message: str = DEFAULT_AUDIO_STATUS,
) -> AudioStatus:
    if state is None:
        return AudioStatus(now_playing=default_title, state="stopped", status_message=fallback_message)
    return AudioStatus(
        now_playing=state.title or default_title,
        state="paused" if state.paused else "playing",
        status_message=("音频已暂停" if state.paused else "音频播放中"),
    )


def _cover_url_from_item(item: VideoItem) -> str | None:
    for key in ("pic", "cover", "cover_url", "coverUrl"):
        value = item.raw.get(key)
        if isinstance(value, str) and value:
            return value if value.startswith("http") else f"https:{value}"
    return None


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
            bvid=f"BV1xx411c7m{index}",
            published_label="阶段 1 占位",
            stat_line=f"播放 {index * 1234}",
            ref_label=f"BV1xx411c7m{index}",
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


def video_cover_url(item: VideoItem | None) -> str | None:
    if item is None:
        return None
    raw = item.raw or {}
    for field in ("pic", "cover", "cover_url", "coverUrl", "vertical_cover"):
        value = raw.get(field)
        if isinstance(value, str) and value.strip():
            if value.startswith("//"):
                return f"https:{value}"
            return value
    return None


def video_summary_from_item(item: VideoItem) -> VideoSummary:
    return VideoSummary(
        title=item.title,
        author=item.author,
        description=item.description or "暂无简介",
        duration=item.duration,
        play_label=f"{human_count(item.play)} 播放",
        url=item.url,
        cover_url=video_cover_url(item),
    )


def comment_summary_from_item(item: CommentItem) -> CommentSummary:
    return CommentSummary(
        author=item.author,
        message=item.message or "暂无评论内容",
        meta=f"👍 {human_count(item.like)} · {format_timestamp(item.ctime)}",
    )


def detail_preview_text(item: VideoItem | None, *, width: int = 42) -> str:
    if item is None:
        return "详情区：当前没有可显示的视频。"
    return "\n".join(build_detail_lines(item, width))


def resolve_video_for_detail(client: object, item: VideoItem | None) -> VideoItem | None:
    if item is None or not hasattr(client, "video"):
        return item
    lookup_ref = video_lookup_ref_from_item(item)
    if not lookup_ref:
        return item
    try:
        resolved = client.video(lookup_ref)
    except (BilibiliAPIError, ValueError):
        return item
    return resolved if isinstance(resolved, VideoItem) else item


def load_comment_summaries(client: object, item: VideoItem | None, *, limit: int = 4) -> tuple[VideoItem | None, list[CommentSummary], str | None]:
    if item is None:
        return None, [], "当前没有可加载评论的视频。"
    resolved = resolve_video_for_detail(client, item)
    if resolved is None:
        return item, [], "当前没有可加载评论的视频。"
    if resolved.aid is None:
        if is_bangumi_item(resolved):
            return resolved, [], "当前番剧条目暂不支持评论预览，请按 o 在浏览器查看。"
        return resolved, [], "当前条目缺少 AID，无法加载评论。"
    if not hasattr(client, "comments"):
        return resolved, [], "当前客户端不可用，无法加载评论。"
    try:
        comments = client.comments(resolved.aid, page_size=limit, bvid=resolved.bvid)
    except BilibiliAPIError as exc:
        return resolved, [], f"评论加载失败: {exc}"
    return resolved, [comment_summary_from_item(comment) for comment in comments], None


def bangumi_badge(item: VideoItem | None) -> str:
    if item is None:
        return "-"
    return "番剧 / PGC" if is_bangumi_item(item) or (item.raw or {}).get("season_type") == COMMENT_WEB_LOCATION else "视频"
