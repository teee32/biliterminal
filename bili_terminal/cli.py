from __future__ import annotations

import argparse
import html
import os
import sys
import webbrowser

from .audio import (
    pause_audio_playback,
    play_audio_for_item,
    read_private_text_once,
    resume_audio_playback,
    run_audio_worker,
    stop_audio_playback,
    toggle_audio_playback,
)
from .client import BilibiliClient
from .history import HistoryStore
from .models import BilibiliAPIError
from .output import print_comments, print_favorite_folders, print_favorites, print_history, print_import_result, print_video_detail, print_video_list
from .qr import qr_svg_data_uri
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

    import_fav_parser = subparsers.add_parser("import-favorites", help="从 Bilibili 服务端导入收藏夹")
    import_fav_parser.add_argument("--folder", type=int, default=None, help="指定收藏夹 ID（默认导入全部）")

    import_hist_parser = subparsers.add_parser("import-history", help="从 Bilibili 服务端导入观看历史")
    import_hist_parser.add_argument("--max", type=int, default=None, help="最多导入 N 条（默认全部）")

    subparsers.add_parser("favorite-folders", help="查看 Bilibili 服务端收藏夹列表")

    subparsers.add_parser("repl", help="进入交互模式")
    subparsers.add_parser("tui", help="进入全屏终端界面")
    subparsers.add_parser("login", help="登录 Bilibili 账号")

    audio_worker_parser = subparsers.add_parser("audio-worker", help=argparse.SUPPRESS)
    audio_worker_parser.add_argument("--url", required=True, help=argparse.SUPPRESS)
    audio_worker_parser.add_argument("--referer", required=True, help=argparse.SUPPRESS)
    audio_worker_parser.add_argument("--user-agent", required=True, help=argparse.SUPPRESS)
    audio_worker_parser.add_argument("--title", default="", help=argparse.SUPPRESS)
    audio_worker_parser.add_argument("--video-key", default="", help=argparse.SUPPRESS)
    audio_worker_parser.add_argument("--cookie-file", default="", help=argparse.SUPPRESS)
    return parser


def build_login_page_html(url: str) -> str:
    safe_url = html.escape(url, quote=True)
    safe_qr = html.escape(qr_svg_data_uri(url), quote=True)
    return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>BiliTerminal 登录</title>
    <style>
        body {{
            background-color: #1a1a1a;
            color: #ffffff;
            font-family: "Helvetica Neue", Helvetica, Arial, sans-serif;
            display: flex;
            justify-content: center;
            align-items: center;
            height: 100vh;
            margin: 0;
        }}
        .card {{
            background-color: #2d2d2d;
            padding: 40px;
            border-radius: 12px;
            text-align: center;
            box-shadow: 0 4px 15px rgba(0, 0, 0, 0.3);
            max-width: 520px;
        }}
        h2 {{
            margin-top: 0;
            color: #fb7299;
        }}
        .qr {{
            width: 260px;
            height: 260px;
            background: #ffffff;
            border-radius: 8px;
            padding: 14px;
            margin: 18px auto;
            box-sizing: border-box;
        }}
        .tips {{
            color: #aaaaaa;
            font-size: 13px;
            line-height: 1.6;
            word-break: break-all;
            margin: 10px 0 0 0;
        }}
        a {{
            color: #fb7299;
            text-decoration: none;
        }}
        a:hover {{
            text-decoration: underline;
        }}
    </style>
</head>
<body>
    <div class="card">
        <h2>BiliTerminal 登录</h2>
        <p>请使用 Bilibili 手机 App 扫描下方二维码。</p>
        <img class="qr" src="{safe_qr}" alt="Bilibili 登录二维码">
        <p class="tips"><a href="{safe_url}" target="_blank" rel="noreferrer">{safe_url}</a></p>
        <p class="tips" style="margin-top: 15px;">二维码在本地生成，不会把登录链接发送给第三方服务。</p>
    </div>
</body>
</html>
"""


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
    if args.command == "import-favorites":
        return _run_import_favorites(args, client, history_store)
    if args.command == "import-history":
        return _run_import_history(args, client, history_store)
    if args.command == "favorite-folders":
        folders = client.user_favorite_folders()
        print_favorite_folders(folders)
        return 0
    if args.command == "tui":
        return run_tui(client, history_store)
    if args.command == "login":
        return run_login(client)
    if args.command == "audio-worker":
        cookie = read_private_text_once(args.cookie_file)
        return run_audio_worker(args.url, args.referer, args.user_agent, args.title, args.video_key or None, cookie=cookie)
    BilibiliCLI(client, history_store).cmdloop()
    return 0


def _run_import_favorites(args: argparse.Namespace, client: BilibiliClient, history_store: HistoryStore) -> int:
    """从 Bilibili 服务端导入收藏夹。"""
    import time
    from .models import BilibiliAPIError

    try:
        if args.folder is not None:
            folders = [{"id": args.folder, "title": f"收藏夹 {args.folder}", "media_count": "?"}]
        else:
            folders = client.user_favorite_folders()
            if not folders:
                print("服务端收藏夹为空或无法获取。")
                return 0
            print_favorite_folders(folders)

        all_items: list = []
        for folder in folders:
            fid = folder["id"]
            title = folder.get("title", f"收藏夹 {fid}")
            print(f"正在导入 [{fid}] {title}...", end="", flush=True)
            page = 1
            folder_items: list = []
            while True:
                items, has_more = client.user_favorite_videos(fid, page=page, page_size=20)
                folder_items.extend(items)
                if not has_more:
                    break
                page += 1
                time.sleep(0.5)
            print(f" {len(folder_items)} 个视频")
            all_items.extend(folder_items)

        count = history_store.replace_favorites(all_items)
        print_import_result("favorites", count)
        return 0
    except BilibiliAPIError as exc:
        print(f"\n导入收藏夹失败: {exc}", file=sys.stderr)
        return 1


def _run_import_history(args: argparse.Namespace, client: BilibiliClient, history_store: HistoryStore) -> int:
    """从 Bilibili 服务端导入观看历史。"""
    import time
    from .models import BilibiliAPIError

    try:
        all_items: list = []
        cursor: dict | None = {}
        page = 0
        while cursor is not None:
            page += 1
            print(f"\r正在获取观看历史 第 {page} 页...", end="", flush=True)
            max_oid = str(cursor.get("max", "")) if isinstance(cursor, dict) else ""
            view_at = int(cursor.get("view_at", 0)) if isinstance(cursor, dict) else 0
            items, cursor = client.user_history(max_oid=max_oid, view_at=view_at, page_size=20)
            all_items.extend(items)
            if args.max is not None and len(all_items) >= args.max:
                all_items = all_items[: args.max]
                break
            if cursor is not None:
                time.sleep(0.5)
        print()  # 换行
        count = history_store.replace_history(all_items)
        print_import_result("history", count)
        return 0
    except BilibiliAPIError as exc:
        print(f"\n导入观看历史失败: {exc}", file=sys.stderr)
        return 1


def run_login(client: BilibiliClient) -> int:
    import webbrowser
    import time

    print("==================================================")
    print("           BiliTerminal 账号登录/配置             ")
    print("==================================================")

    # 支持纯 CLI 环境下手动输入 Cookie
    user_cookie = input("请输入 Bilibili Cookie (直接回车将使用本地二维码登录): ").strip()
    if user_cookie:
        try:
            client._set_cookie_string(user_cookie)
            client.save_session()
            print("\n[+] Cookie 配置成功并已保存！")
            return 0
        except Exception as exc:
            print(f"\n[-] 保存 Cookie 失败: {exc}")
            return 1

    # 如果用户直接回车，则进行本地二维码登录确认
    print("\n[+] 正在请求登录二维码...")
    temp_html_path = ""
    try:
        qr_data = client.login_qrcode_generate()
        url = qr_data.get("url")
        qrcode_key = qr_data.get("qrcode_key")
        if not url or not qrcode_key:
            print("[-] 获取登录二维码失败: 接口返回数据不完整")
            return 1

        print("\n[+] 登录二维码请求成功！")
        print("请使用 Bilibili 手机 App 扫描浏览器里的本地二维码。扫码链接如下:\n")
        print(f"  {url}")
        print("\n--------------------------------------------------")

        # 生成一个本地二维码登录页面。登录 URL 本身是凭据，不交给第三方服务。
        import tempfile
        try:
            with tempfile.NamedTemporaryFile(suffix=".html", delete=False, mode="w", encoding="utf-8") as f:
                f.write(build_login_page_html(url))
                temp_html_path = f.name
        except Exception as exc:
            print(f"[!] 创建临时登录页面失败: {exc}")

        # 尝试使用 webbrowser 自动打开本地登录 HTML 文件
        try:
            if temp_html_path:
                webbrowser.open(f"file://{temp_html_path}")
                print("[+] 已自动在您的默认浏览器中打开本地二维码页面。")
            else:
                webbrowser.open(url)
                print("[+] 已自动在您的默认浏览器中打开登录链接。")
        except Exception:
            print("[!] 未能自动打开浏览器，请手动复制上面的链接。")

        print("[-] 正在等待您确认登录 (可按 Ctrl+C 取消)...")

        # 轮询登录确认状态
        expired = False
        while not expired:
            time.sleep(2)
            try:
                poll_res = client.login_qrcode_poll(qrcode_key)
                code = poll_res.get("code", -1)
                message = poll_res.get("message", "未知状态")

                if code == 0:
                    print("\n[+] 登录成功！欢迎使用！")
                    return 0
                elif code == 86101:
                    # 未确认
                    sys.stdout.write(".")
                    sys.stdout.flush()
                elif code == 86090:
                    # 已打开未确认
                    sys.stdout.write("o")
                    sys.stdout.flush()
                elif code == 86038:
                    print("\n[-] 登录二维码已过期，请重新运行登录命令。")
                    expired = True
                else:
                    print(f"\n[-] 轮询状态异常: code={code}, message={message}")
                    expired = True
            except KeyboardInterrupt:
                print("\n[!] 登录已被用户取消。")
                return 0
            except Exception as exc:
                print(f"\n[-] 轮询出错: {exc}")
                expired = True

        return 1
    except Exception as exc:
        print(f"[-] 登录失败: {exc}")
        return 1
    finally:
        if temp_html_path and os.path.exists(temp_html_path):
            try:
                os.unlink(temp_html_path)
            except Exception:
                pass


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
