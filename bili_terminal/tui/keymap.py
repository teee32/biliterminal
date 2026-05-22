from __future__ import annotations

APP_CHANNEL_SHORTCUT_KEYS = tuple("1234567890")

APP_BINDING_SPECS = (
    ("up", "move_up"),
    ("down", "move_down"),
    ("j", "move_up"),
    ("k", "move_down"),
    ("enter", "show_detail"),
    ("escape", "go_back"),
    ("b", "go_back"),
    ("slash", "focus_search"),
    ("s", "focus_search"),
    ("tab", "next_channel"),
    ("shift+tab", "prev_channel"),
    ("l", "rerun_last_search"),
    ("d", "default_search"),
    ("h", "go_home"),
    ("v", "show_history"),
    ("m", "show_favorites"),
    ("w", "show_watch_later"),
    ("W", "toggle_watch_later"),
    ("f", "toggle_favorite"),
    ("a", "toggle_audio"),
    ("x", "stop_audio"),
    ("n", "next_page"),
    ("p", "prev_page"),
    ("pageup", "detail_page_up"),
    ("pagedown", "detail_page_down"),
    ("o", "open_in_browser"),
    ("c", "refresh_comments"),
    ("r", "refresh_view"),
    ("ctrl+t", "toggle_theme"),
    ("f2", "toggle_theme"),
    ("question_mark", "toggle_help"),
    ("q", "quit"),
)

KEYMAP_HELP_GROUPS = (
    ("up/down", "↑/↓ / j/k", "移动", ("up", "down", "j", "k")),
    ("detail", "Enter", "详情", ("enter",)),
    ("back", "Esc / b", "返回", ("escape", "b")),
    ("search", "/ / s", "搜索", ("slash", "s")),
    ("channels-cycle", "Tab / Shift+Tab", "切换分区", ("tab", "shift+tab")),
    ("channels-jump", "1-9 / 0", "直选分区", APP_CHANNEL_SHORTCUT_KEYS),
    ("search-repeat", "l", "最近搜索", ("l",)),
    ("search-default", "d", "默认搜索词", ("d",)),
    ("home", "h", "首页", ("h",)),
    ("history", "v", "历史", ("v",)),
    ("favorites-view", "m", "收藏夹", ("m",)),
    ("watch-later-view", "w", "稍后看", ("w",)),
    ("watch-later-toggle", "Shift+W", "稍后看开关", ("W",)),
    ("favorite-toggle", "f", "收藏", ("f",)),
    ("audio-toggle", "a", "播放/暂停", ("a",)),
    ("audio-stop", "x", "停止", ("x",)),
    ("paging", "n / p", "翻页", ("n", "p")),
    ("detail-scroll", "PgUp / PgDn", "详情滚动", ("pageup", "pagedown")),
    ("browser", "o", "浏览器打开", ("o",)),
    ("comments", "c", "评论", ("c",)),
    ("refresh", "r", "刷新", ("r",)),
    ("theme", "Ctrl+T / F2", "切换主题", ("ctrl+t", "f2")),
    ("help", "?", "帮助", ("question_mark",)),
    ("quit", "q", "退出", ("q",)),
)

KEYMAP_GROUPS = tuple((section, legend, keys) for section, legend, _, keys in KEYMAP_HELP_GROUPS)
KEYMAP_SUMMARY = [(section, legend) for section, legend, _, _ in KEYMAP_HELP_GROUPS]
HELP_LINES = [f"{legend} {label}" for _, legend, label, _ in KEYMAP_HELP_GROUPS]

KEYMAP_HELP_BY_ID = {group_id: (legend, label, keys) for group_id, legend, label, keys in KEYMAP_HELP_GROUPS}


def keymap_hint(*group_ids: str, separator: str = " · ") -> str:
    return separator.join(
        f"{KEYMAP_HELP_BY_ID[group_id][0]} {KEYMAP_HELP_BY_ID[group_id][1]}"
        for group_id in group_ids
    )


HOME_SUBTITLE_TEXT = keymap_hint("channels-cycle", "channels-jump", separator=" / ")
HOME_SIDEBAR_INTRO_TEXT = keymap_hint("channels-cycle", "channels-jump", separator="\n")
HOME_FEED_HINT_TEXT = keymap_hint(
    "up/down",
    "detail",
    "comments",
    "browser",
    "watch-later-toggle",
    "favorite-toggle",
    "audio-toggle",
    "audio-stop",
)
DETAIL_HINT_TEXT = keymap_hint(
    "up/down",
    "detail-scroll",
    "audio-toggle",
    "audio-stop",
    "watch-later-toggle",
    "favorite-toggle",
    "comments",
    "back",
)
HISTORY_SUBTITLE_TEXT = f"最近浏览 · {keymap_hint('detail', 'browser', 'audio-toggle', 'audio-stop')}"
FAVORITES_SUBTITLE_TEXT = f"收藏夹 · {keymap_hint('favorite-toggle', 'detail', 'browser')}"
WATCH_LATER_SUBTITLE_TEXT = f"稍后看队列 · {keymap_hint('watch-later-toggle', 'detail', 'browser')}"
WATCH_LATER_FEED_HINT_TEXT = keymap_hint(
    "up/down",
    "detail",
    "browser",
    "watch-later-toggle",
)
THEME_PICKER_HINT_TEXT = keymap_hint("up/down", "detail", "back")
THEME_TOGGLE_SOURCE_TEXT = KEYMAP_HELP_BY_ID["theme"][0]
THEME_MENU_SOURCE_TEXT = "主题菜单"
SEARCH_SUBTITLE_TEXT = f"支持中文实时输入 · {keymap_hint('detail', 'search-repeat', 'search-default')}"
SEARCH_EMPTY_PROMPT_TEXT = "请输入关键词后按 Enter 开始搜索"
SEARCH_PLACEHOLDER_TEXT = "按 / 或 s 搜索，支持中文实时输入"
