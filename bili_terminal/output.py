from __future__ import annotations

import textwrap

from .history import HistoryStore
from .models import CommentItem, VideoItem
from .textutil import format_timestamp, human_count, shorten, wrap_display


def print_video_list(items: list[VideoItem], title: str) -> None:
    print(f"\n{title}")
    print("=" * len(title))
    if not items:
        print("没有结果。")
        return
    for index, item in enumerate(items, start=1):
        meta = (
            f"UP: {item.author} | 播放: {human_count(item.play)} | "
            f"弹幕: {human_count(item.danmaku)} | 时长: {item.duration} | "
            f"发布时间: {format_timestamp(item.pubdate)}"
        )
        print(f"{index:>2}. {shorten(item.title, 72)}")
        print(f"    {meta}")
        print(f"    {item.bvid or item.aid} | {item.url}")
    print("\n提示: 可用 `video 1` 查看详情，`audio 1` 播放音频，`favorite 1` 加入收藏，或 `open 1` 在浏览器中打开。")


def print_video_detail(item: VideoItem) -> None:
    print(f"\n{item.title}")
    print("=" * len(item.title))
    print(f"UP主: {item.author}")
    print(f"BV号: {item.bvid or '-'}")
    print(f"AID: {item.aid or '-'}")
    print(f"时长: {item.duration}")
    print(f"发布时间: {format_timestamp(item.pubdate)}")
    print(f"播放: {human_count(item.play)}  弹幕: {human_count(item.danmaku)}")
    print(f"点赞: {human_count(item.like)}  收藏: {human_count(item.favorite)}")
    print(f"链接: {item.url}")
    if item.description:
        print("\n简介:")
        print(textwrap.fill(item.description, width=88))


def print_history(history_store: HistoryStore) -> None:
    print("\n最近搜索")
    print("========")
    keywords = history_store.get_recent_keywords(10)
    if keywords:
        for index, keyword in enumerate(keywords, start=1):
            print(f"{index:>2}. {keyword}")
    else:
        print("没有搜索记录。")

    print("\n最近浏览")
    print("========")
    videos = history_store.get_recent_videos(10)
    if not videos:
        print("没有视频记录。")
        return
    for index, item in enumerate(videos, start=1):
        print(f"{index:>2}. {shorten(item.title, 72)}")
        print(f"    {item.author} | {item.bvid or item.aid} | {item.url}")


def print_favorites(history_store: HistoryStore) -> None:
    print("\n收藏夹")
    print("======")
    favorites = history_store.get_favorite_videos()
    if not favorites:
        print("收藏夹为空。")
        return
    for index, item in enumerate(favorites, start=1):
        print(f"{index:>2}. {shorten(item.title, 72)}")
        print(f"    {item.author} | {item.bvid or item.aid} | {item.url}")
    print("\n提示: 可用 `audio 1` 播放音频，`favorites open 1` 直接打开，或 `favorites remove 1` 从收藏夹移除。")


def print_comments(item: VideoItem, comments: list[CommentItem]) -> None:
    title = f"热评预览: {shorten(item.title, 72)}"
    print(f"\n{title}")
    print("=" * len(title))
    if not comments:
        print("没有可显示的评论。")
        return
    for index, comment in enumerate(comments, start=1):
        print(f"{index:>2}. {comment.author} | {human_count(comment.like)} 赞 | {format_timestamp(comment.ctime)}")
        print(textwrap.fill(comment.message or "暂无评论内容", width=88, initial_indent="    ", subsequent_indent="    "))


def build_detail_lines(item: VideoItem, width: int) -> list[str]:
    title_lines = wrap_display(item.title, width=max(20, width))
    description_lines = wrap_display(item.description, width=max(20, width)) if item.description else ["无简介"]
    return [
        *title_lines,
        "",
        f"👤 UP主: {item.author}",
        f"🔗 BV号: {item.bvid or '-'}",
        f"🔗 AID: {item.aid or '-'}",
        f"🕒 时长: {item.duration}",
        f"📅 发布时间: {format_timestamp(item.pubdate)}",
        f"▶ 播放: {human_count(item.play)}",
        f"≡ 弹幕: {human_count(item.danmaku)}",
        f"👍 点赞: {human_count(item.like)}",
        f"⭐ 收藏: {human_count(item.favorite)}",
        f"🌐 链接: {item.url}",
        "",
        "📝 简介:",
        *description_lines,
    ]
