# BiliTerminal Textual v0.3.1 架构说明

> 当前仓库已经收束为 Textual TUI-only。用户入口只启动新版 Textual，旧命令行浏览器和旧终端 UI 不再作为产品面暴露。

## 发布与入口策略

- `./biliterminal` / `./bili_terminal/start.sh`：默认进入 Textual UI
- `python3 -m bili_terminal`：默认进入 Textual UI
- `textual` / `new-tui` / `tui` / `--tui`：保留为 Textual 别名
- `pyproject.toml` 提供 `biliterminal` console script，与仓库脚本保持同一套启动语义
- `bili_terminal/core.py` 保留为内部 core 和音频 worker 承载文件，不暴露浏览型 CLI

## 目录结构

```text
bili_terminal/
├── __main__.py
├── core.py
├── tui/
│   ├── __init__.py
│   ├── app.py
│   ├── keymap.py
│   ├── screens/
│   │   ├── __init__.py
│   │   ├── home.py
│   │   ├── search.py
│   │   ├── detail.py
│   │   ├── favorites.py
│   │   ├── history.py
│   │   ├── theme_picker.py
│   │   └── watch_later.py
│   ├── widgets/
│   │   ├── __init__.py
│   │   ├── video_list.py
│   │   ├── audio_bar.py
│   │   └── comment_view.py
│   ├── styles/
│   │   └── bili_dark.tcss
│   └── utils.py
└── tests/
```

## 当前实现要点

### 1. App 层

`bili_terminal/tui/app.py` 负责：

- 注册 Textual 快捷键
- 统一调度 Home / Search / Detail / History / Favorites / WatchLater Screen
- 维护全局音频状态并同步到底部 `AudioBar`
- 保留 Textual 缺依赖时的友好报错

### 2. Screen 层

- `HomeScreen`：首页推荐、分区切换、0/1-9 直选、分页、预览面板
- `SearchScreen`：中文输入、Enter 搜索、最近搜索、默认搜索词
- `DetailScreen`：详情滚动、评论刷新、收藏、稍后看、音频控制、浏览器打开
- `HistoryScreen`：最近浏览
- `FavoritesScreen`：收藏夹与取消收藏
- `WatchLaterScreen`：本地稍后看队列，手动移出

### 3. Widget 层

- `VideoList`：键盘/鼠标统一列表交互
- `CommentView`：评论预览与错误/空态展示
- `AudioBar`：全局播放状态展示

### 4. Theme 层

- `dark`：默认深色主题
- `light`：浅色主题
- `claude`：暖纸张底色、陶土强调色的 Claude 风格主题
- 主题配置写入 `~/.biliterminal/config.toml`，也支持通过 `BILITERMINAL_CONFIG` 指向测试/自定义路径

### 5. 业务逻辑复用

Textual UI 通过 `bili_terminal/tui/utils.py` 中的 `TextualAdapter` 复用 core：

- `BilibiliClient`
- `HistoryStore`
- 详情/评论/音频/收藏/稍后看相关纯函数与状态函数

## 快捷键

Textual 版已覆盖并验证以下键位：

- `↑/↓ / j/k`
- `Enter`
- `Esc / b`
- `/ / s`
- `Tab / Shift+Tab`
- `1-9 / 0`
- `l / d / h / v / m / w / Shift+W / f / a / x`
- `n / p`
- `PgUp / PgDn`
- `o / c / r / ? / q`

## 打包与验证

- `build_macos_app.sh` 会复制完整 `bili_terminal/tui/` 资源树和内部 core/audio worker
- `bili_terminal/tests/test_build_macos_app.py` 覆盖 Textual 资源打包回归
- `bili_terminal/tests/test_textual_app.py` 覆盖 Textual 启动、分区快捷键、搜索/详情/返回、历史/收藏/稍后看流转
- 全量测试：`python3 -m unittest discover -s bili_terminal/tests -v`

## 结论

v0.3.0 的 Textual 版是仓库唯一用户产品路径。core 文件继续承载 API、存储、格式化和音频 worker，避免复制业务逻辑到 UI 层。
