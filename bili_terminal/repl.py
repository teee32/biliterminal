from __future__ import annotations

import cmd
import shlex
import webbrowser

from . import audio
from .client import BilibiliClient
from .history import HistoryStore
from .models import (
    BilibiliAPIError,
    VideoItem,
    build_watch_url,
    parse_video_ref,
    video_key_from_item,
    video_key_from_ref,
)
from .output import print_comments, print_favorites, print_history, print_video_detail, print_video_list


def open_video_target(target: str) -> str:
    ref_type, value = parse_video_ref(target)
    url = build_watch_url(ref_type, value)
    webbrowser.open(url)
    return url


class BilibiliCLI(cmd.Cmd):
    intro = (
        "Bilibili CLI 已启动。\n"
        "可用命令: hot [页码] [数量], search <关键词> [页码] [数量], "
        "video <BV号|av号|URL|序号>, audio <序号|BV号|URL|pause|resume|toggle|stop>, "
        "favorite <序号|BV号|URL>, favorites [open|remove], open <序号|BV号|URL>, exit"
    )
    prompt = "bili> "

    def __init__(self, client: BilibiliClient, history_store: HistoryStore | None = None) -> None:
        super().__init__()
        self.client = client
        self.history_store = history_store or HistoryStore()
        self.last_items: list[VideoItem] = []

    def emptyline(self) -> bool:
        return False

    def do_hot(self, arg: str) -> None:
        parts = shlex.split(arg)
        page = int(parts[0]) if len(parts) >= 1 else 1
        limit = int(parts[1]) if len(parts) >= 2 else 10
        items = self.client.popular(page=page, page_size=limit)
        self.last_items = items
        print_video_list(items, f"热门视频 第 {page} 页")

    def do_search(self, arg: str) -> None:
        parts = shlex.split(arg)
        if not parts:
            print("用法: search <关键词> [页码] [数量]")
            return
        page = 1
        limit = 10
        if len(parts) >= 2 and parts[-1].isdigit():
            limit = int(parts.pop())
        if len(parts) >= 2 and parts[-1].isdigit():
            page = int(parts.pop())
        keyword = " ".join(parts)
        items = self.client.search(keyword=keyword, page=page, page_size=limit)
        self.history_store.add_keyword(keyword)
        self.last_items = items
        print_video_list(items, f"搜索结果: {keyword} | 第 {page} 页")

    def do_video(self, arg: str) -> None:
        if not arg.strip():
            print("用法: video <BV号|av号|URL|序号>")
            return
        target = self._resolve_target(arg.strip())
        item = self.client.video(target)
        self.history_store.add_video(item)
        print_video_detail(item)

    def do_history(self, _: str) -> None:
        self.last_items = self.history_store.get_recent_videos(10)
        print_history(self.history_store)

    def do_favorite(self, arg: str) -> None:
        if not arg.strip():
            print("用法: favorite <序号|BV号|av号|URL>")
            return
        item = self._resolve_item_for_favorite(arg.strip())
        added = self.history_store.add_favorite(item)
        status = "已收藏" if added else "收藏夹已更新"
        print(f"{status}: {item.title}")

    def do_favorites(self, arg: str) -> None:
        parts = shlex.split(arg)
        if not parts:
            favorites = self.history_store.get_favorite_videos()
            self.last_items = favorites
            print_favorites(self.history_store)
            return
        action = parts[0].lower()
        if action == "open" and len(parts) >= 2:
            item = self._resolve_favorite_item(parts[1])
            webbrowser.open(item.url)
            self.history_store.add_video(item)
            print(f"已打开收藏: {item.url}")
            return
        if action == "remove" and len(parts) >= 2:
            item = self._resolve_favorite_item(parts[1])
            self.history_store.remove_favorite(item)
            print(f"已移出收藏: {item.title}")
            return
        print("用法: favorites [open <序号|BV号|av号|URL> | remove <序号|BV号|av号|URL>]")

    def do_comments(self, arg: str) -> None:
        if not arg.strip():
            print("用法: comments <BV号|av号|URL|序号> [数量]")
            return
        parts = shlex.split(arg)
        limit = 5
        if parts[-1].isdigit() and len(parts) > 1:
            limit = int(parts.pop())
        target = self._resolve_target(" ".join(parts))
        item = self.client.video(target)
        if item.aid is None:
            raise ValueError("当前视频缺少 AID，无法加载评论")
        comments = self.client.comments(item.aid, page_size=limit, bvid=item.bvid)
        print_comments(item, comments)

    def do_open(self, arg: str) -> None:
        if not arg.strip():
            print("用法: open <序号|BV号|URL>")
            return
        target = arg.strip()
        if target.isdigit() and self.last_items:
            index = int(target) - 1
            if index < 0 or index >= len(self.last_items):
                print(f"序号超出范围: {target}")
                return
            item = self.last_items[index]
            self.history_store.add_video(item)
            url = item.url
        else:
            try:
                key, value = parse_video_ref(target)
                url = build_watch_url(key, value)
            except ValueError:
                url = target
        webbrowser.open(url)
        print(f"已打开: {url}")

    def do_audio(self, arg: str) -> None:
        if not arg.strip():
            print("用法: audio <序号|BV号|av号|URL|pause|resume|toggle|stop>")
            return
        action = arg.strip().lower()
        if action == "pause":
            print(audio.pause_audio_playback())
            return
        if action == "resume":
            print(audio.resume_audio_playback())
            return
        if action == "toggle":
            print(audio.toggle_audio_playback())
            return
        if action == "stop":
            print(audio.stop_audio_playback())
            return
        item = self._resolve_item_for_favorite(arg.strip())
        self.history_store.add_video(item)
        print(audio.play_audio_for_item(self.client, item))

    def do_exit(self, _: str) -> bool:
        return True

    def do_quit(self, _: str) -> bool:
        return True

    def do_EOF(self, _: str) -> bool:
        print()
        return True

    def _resolve_target(self, target: str) -> str:
        if target.isdigit() and self.last_items:
            index = int(target) - 1
            if index < 0 or index >= len(self.last_items):
                raise ValueError(f"序号超出范围: {target}")
            item = self.last_items[index]
            return item.bvid or str(item.aid)
        return target

    def _resolve_item_for_favorite(self, target: str) -> VideoItem:
        if target.isdigit() and self.last_items:
            index = int(target) - 1
            if index < 0 or index >= len(self.last_items):
                raise ValueError(f"序号超出范围: {target}")
            return self.last_items[index]
        return self.client.video(self._resolve_target(target))

    def _resolve_favorite_item(self, target: str) -> VideoItem:
        favorites = self.history_store.get_favorite_videos()
        if target.isdigit():
            index = int(target) - 1
            if index < 0 or index >= len(favorites):
                raise ValueError(f"收藏夹序号超出范围: {target}")
            return favorites[index]
        ref_type, value = parse_video_ref(target)
        target_key = video_key_from_ref(ref_type, value)
        for item in favorites:
            if video_key_from_item(item) == target_key:
                return item
        raise ValueError("收藏夹中不存在该视频")

    def onecmd(self, line: str) -> bool:
        try:
            return super().onecmd(line)
        except (BilibiliAPIError, ValueError) as exc:
            print(f"错误: {exc}")
            return False
