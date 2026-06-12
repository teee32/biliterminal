from __future__ import annotations

import argparse
import sys
import webbrowser

from .audio import (
    pause_audio_playback,
    play_audio_for_item,
    resume_audio_playback,
    run_audio_worker,
    stop_audio_playback,
    toggle_audio_playback,
)
from .client import BilibiliClient
from .history import HistoryStore
from .models import BilibiliAPIError
from .output import print_comments, print_favorites, print_history, print_video_detail, print_video_list
from .repl import BilibiliCLI, open_video_target
from .tui import run_tui


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="把 Bilibili 常用浏览操作搬到终端里。")
    subparsers = parser.add_subparsers(dest="command")

    hot_parser = subparsers.add_parser("hot", help="查看热门视频")
    hot_parser.add_argument("-p", "--page", type=int, default=1, help="页码")
    hot_parser.add_argument("-n", "--limit", type=int, default=10, help="数量")

    search_parser = subparsers.add_parser("search", help="搜索视频")
    search_parser.add_argument("keyword", help="关键词")
    search_parser.add_argument("-p", "--page", type=int, default=1, help="页码")
    search_parser.add_argument("-n", "--limit", type=int, default=10, help="数量")

    comments_parser = subparsers.add_parser("comments", help="查看视频热评")
    comments_parser.add_argument("ref", help="BV号 / av号 / URL")
    comments_parser.add_argument("-n", "--limit", type=int, default=5, help="数量")

    recommend_parser = subparsers.add_parser("recommend", help="查看首页推荐流")
    recommend_parser.add_argument("-p", "--page", type=int, default=1, help="页码")
    recommend_parser.add_argument("-n", "--limit", type=int, default=10, help="数量")

    precious_parser = subparsers.add_parser("precious", help="查看入站必刷")
    precious_parser.add_argument("-p", "--page", type=int, default=1, help="页码")
    precious_parser.add_argument("-n", "--limit", type=int, default=10, help="数量")

    trending_parser = subparsers.add_parser("trending", help="查看首页热搜词")
    trending_parser.add_argument("-n", "--limit", type=int, default=10, help="数量")

    video_parser = subparsers.add_parser("video", help="查看视频详情")
    video_parser.add_argument("ref", help="BV号 / av号 / URL")

    open_parser = subparsers.add_parser("open", help="浏览器打开视频")
    open_parser.add_argument("ref", help="BV号 / av号 / URL")

    audio_parser = subparsers.add_parser("audio", help="播放或控制视频音频")
    audio_parser.add_argument("ref", help="BV号 / av号 / URL / pause / resume / toggle / stop")

    favorite_parser = subparsers.add_parser("favorite", help="将视频加入收藏夹")
    favorite_parser.add_argument("ref", help="BV号 / av号 / URL")

    favorites_parser = subparsers.add_parser("favorites", help="查看或操作收藏夹")
    favorites_subparsers = favorites_parser.add_subparsers(dest="favorites_action")
    favorites_open_parser = favorites_subparsers.add_parser("open", help="浏览器打开收藏夹中的视频")
    favorites_open_parser.add_argument("ref", help="收藏夹序号 / BV号 / av号 / URL")
    favorites_remove_parser = favorites_subparsers.add_parser("remove", help="从收藏夹移除视频")
    favorites_remove_parser.add_argument("ref", help="收藏夹序号 / BV号 / av号 / URL")

    subparsers.add_parser("history", help="查看最近搜索和最近浏览")
    subparsers.add_parser("repl", help="进入交互模式")
    subparsers.add_parser("tui", help="进入全屏终端界面")

    audio_worker_parser = subparsers.add_parser("audio-worker", help=argparse.SUPPRESS)
    audio_worker_parser.add_argument("--url", required=True, help=argparse.SUPPRESS)
    audio_worker_parser.add_argument("--referer", required=True, help=argparse.SUPPRESS)
    audio_worker_parser.add_argument("--user-agent", required=True, help=argparse.SUPPRESS)
    audio_worker_parser.add_argument("--title", default="", help=argparse.SUPPRESS)
    audio_worker_parser.add_argument("--video-key", default="", help=argparse.SUPPRESS)
    return parser


def run_once(args: argparse.Namespace, client: BilibiliClient, history_store: HistoryStore) -> int:
    if args.command == "hot":
        print_video_list(client.popular(page=args.page, page_size=args.limit), f"热门视频 第 {args.page} 页")
        return 0
    if args.command == "recommend":
        print_video_list(client.recommend(page=args.page, page_size=args.limit), f"首页推荐 第 {args.page} 页")
        return 0
    if args.command == "precious":
        print_video_list(client.precious(page=args.page, page_size=args.limit), f"入站必刷 第 {args.page} 页")
        return 0
    if args.command == "search":
        items = client.search(keyword=args.keyword, page=args.page, page_size=args.limit)
        history_store.add_keyword(args.keyword)
        print_video_list(items, f"搜索结果: {args.keyword} | 第 {args.page} 页")
        return 0
    if args.command == "comments":
        item = client.video(args.ref)
        if item.aid is None:
            raise ValueError("当前视频缺少 AID，无法加载评论")
        print_comments(item, client.comments(item.aid, args.limit, bvid=item.bvid))
        return 0
    if args.command == "trending":
        print("\n首页热搜")
        print("========")
        for index, keyword in enumerate(client.trending_keywords(args.limit), start=1):
            print(f"{index:>2}. {keyword}")
        return 0
    if args.command == "video":
        item = client.video(args.ref)
        history_store.add_video(item)
        print_video_detail(item)
        return 0
    if args.command == "open":
        url = open_video_target(args.ref)
        print(f"已打开: {url}")
        return 0
    if args.command == "audio":
        action = args.ref.lower()
        if action == "pause":
            print(pause_audio_playback())
            return 0
        if action == "resume":
            print(resume_audio_playback())
            return 0
        if action == "toggle":
            print(toggle_audio_playback())
            return 0
        if action == "stop":
            print(stop_audio_playback())
            return 0
        item = client.video(args.ref)
        history_store.add_video(item)
        print(play_audio_for_item(client, item))
        return 0
    if args.command == "favorite":
        item = client.video(args.ref)
        added = history_store.add_favorite(item)
        print(f"{'已收藏' if added else '收藏夹已更新'}: {item.title}")
        return 0
    if args.command == "favorites":
        action = getattr(args, "favorites_action", None)
        if action is None:
            print_favorites(history_store)
            return 0
        shell = BilibiliCLI(client, history_store)
        if action == "open":
            item = shell._resolve_favorite_item(args.ref)
            webbrowser.open(item.url)
            history_store.add_video(item)
            print(f"已打开收藏: {item.url}")
            return 0
        if action == "remove":
            item = shell._resolve_favorite_item(args.ref)
            history_store.remove_favorite(item)
            print(f"已移出收藏: {item.title}")
            return 0
    if args.command == "history":
        print_history(history_store)
        return 0
    if args.command == "tui":
        return run_tui(client, history_store)
    if args.command == "audio-worker":
        return run_audio_worker(args.url, args.referer, args.user_agent, args.title, args.video_key or None)
    BilibiliCLI(client, history_store).cmdloop()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    client = BilibiliClient()
    history_store = HistoryStore()
    try:
        return run_once(args, client, history_store)
    except (BilibiliAPIError, ValueError) as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1
