# BiliTerminal Textual v0.3.0 架构说明

> 当前仓库已经完成 v0.3.0 的 Textual UI 主流程，同时继续保留 legacy curses TUI 作为默认/回退入口。

## 发布与入口策略

- `./biliterminal` / `./bili_terminal/start.sh`：默认进入 legacy curses TUI
- `./biliterminal textual` / `python3 -m bili_terminal textual`：显式进入 Textual UI
- `./biliterminal --legacy-tui` / `python3 -m bili_terminal --legacy-tui`：强制 legacy fallback
- `pyproject.toml` 提供 `biliterminal` console script，与仓库脚本保持同一套参数语义

## 目录结构

```text
bili_terminal/
├── tui/
│   ├── __init__.py
│   ├── app.py
│   ├── screens/
│   │   ├── __init__.py
│   │   ├── home.py
│   │   ├── search.py
│   │   ├── detail.py
│   │   ├── favorites.py
│   │   └── history.py
│   ├── widgets/
│   │   ├── __init__.py
│   │   ├── video_list.py
│   │   ├── audio_bar.py
│   │   └── comment_view.py
│   ├── styles/
│   │   └── bili_dark.tcss
│   └── utils.py
├── bilibili_cli.py
└── tests/
```

## 当前实现要点

### 1. App 层

`bili_terminal/tui/app.py` 负责：

- 注册全部 legacy 快捷键
- 统一调度 Home / Search / Detail / History / Favorites Screen
- 维护全局音频状态并同步到底部 `AudioBar`
- 保留 Textual 缺依赖时的友好报错

### 2. Screen 层

- `HomeScreen`：首页推荐、分区切换、0/1-9 直选、分页、预览面板
- `SearchScreen`：中文输入、Enter 搜索、最近搜索、默认搜索词
- `DetailScreen`：详情滚动、评论刷新、收藏、音频控制、浏览器打开
- `HistoryScreen`：最近浏览
- `FavoritesScreen`：收藏夹与取消收藏

### 3. Widget 层

- `VideoList`：键盘/鼠标统一列表交互
- `CommentView`：评论预览与错误/空态展示
- `AudioBar`：全局播放状态展示

### 4. 业务逻辑复用

Textual UI 不改写已有核心业务，而是通过 `bili_terminal/tui/utils.py` 中的 `TextualAdapter` 复用：

- `BilibiliClient`
- `HistoryStore`
- 详情/评论/音频/收藏相关纯函数与状态函数

## 快捷键对齐

Textual 版已对齐并验证以下键位：

- `↑/↓ / j/k`
- `Enter`
- `Esc / b`
- `/ / s`
- `Tab / Shift+Tab`
- `1-9 / 0`
- `l / d / h / v / m / f / a / x`
- `n / p`
- `PgUp / PgDn`
- `o / c / r / ? / q`

## 打包与验证

- `build_macos_app.sh` 会继续保留 legacy 入口并复制完整 `bili_terminal/tui/` 资源树
- `bili_terminal/tests/test_build_macos_app.py` 覆盖 Textual 资源打包回归
- `bili_terminal/tests/test_textual_app.py` 覆盖 Textual 启动、分区快捷键、搜索/详情/返回、历史/收藏流转
- 全量测试：`python3 -m unittest discover -s bili_terminal/tests -v`

## 结论

v0.3.0 的 Textual 版已经从“骨架预览”提升为可实际使用的主流程实现；默认入口仍保守地保持在 legacy curses TUI，便于继续兼容老终端与打包场景。
