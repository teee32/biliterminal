# BiliTerminal Textual 重构阶段 1 架构说明

> 目标：按 v0.3.0 的迁移方向，为 Textual 版先落下**完整目录结构**、`app.py` 主入口、`HomeScreen` 首页骨架与后续 `core/` 抽离计划，同时保持现有 CLI / curses TUI 完全可用。

## v0.3.0 发布面整合策略

- 默认仓库启动脚本（`./biliterminal`、`./bili_terminal/start.sh`）继续落到 legacy curses TUI，降低发布风险。
- `textual` / `new-tui` 作为显式新入口，统一由 `python -m bili_terminal ...` 分发到 Textual app。
- `legacy-tui` / `--legacy-tui` 作为显式 fallback，要求在仓库脚本、模块入口、安装后的 console script 上语义一致。
- `pyproject.toml` 提供 `biliterminal` console script，保证安装后入口与仓库脚本保持一致。

## 阶段 1 当前落地范围

已落地：

- `bili_terminal/tui/` 新包与主入口 `app.py`
- `screens/` 与 `widgets/` 子目录
- `HomeScreen` + Sidebar / VideoList / Detail / CommentView / AudioBar 骨架
- `styles/bili_dark.tcss`
- `pyproject.toml` 里的 Textual 运行时依赖
- `bili_terminal/tests/test_textual_app.py` smoke tests

暂缓到后续阶段：

- 将 `tui` 默认入口切到 Textual
- `--legacy-tui` 参数
- 真正的 `core/` 目录与业务逻辑抽离
- 图片懒加载 / 渐变动画 / 真实 API 接线 / 音频链路接线

## 目标目录结构（按 v0.3.0 约束）

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
├── core/                         # 阶段 2 起逐步建立
└── bilibili_cli.py               # 现阶段仍是稳定入口与业务真相源
```

## 阶段 1 详细计划（Architect 版本）

### 1. 先搭“壳”，不抢着拆业务

当前 `bilibili_cli.py` 同时承担：

- 数据模型
- API 请求与解析
- 音频控制
- 收藏 / 历史状态
- CLI / REPL
- curses TUI

阶段 1 不改这些业务事实，只做 **Textual UI 壳层**，避免一上来就把运行中的能力拆坏。

### 1.5 发布入口与 screen flow

当前阶段的发布面不把 Textual 直接设为默认，而是明确区分两条入口：

1. **稳定入口**：`./biliterminal`、`./bili_terminal/start.sh`、`biliterminal --legacy-tui` → legacy curses TUI
2. **新 UI 入口**：`./biliterminal textual`、`python -m bili_terminal textual` → Textual Home shell

Textual 侧的 screen flow 约束如下：

- Launch → `HomeScreen`（统一承接全局快捷键与 AudioBar）
- `HomeScreen` 内承载 Search / Detail / History / Favorites 的模式切换或后续独立 Screen push
- legacy curses TUI 继续作为任何发布问题下的回退路径，不与 Textual 快捷键语义分叉

### 2. Textual 壳层职责边界

#### `tui/app.py`
- 定义 `BiliTerminalApp`
- 注册全量原键位
- 将键位 action 转发到当前 Screen
- 提供 `create_app()` / `run_textual_app()`

#### `screens/home.py`
- 首页主布局
- Sidebar / VideoList / Detail / CommentView / AudioBar 组合
- Home / Search / Detail / History / Favorites 五种模式的占位切换语义
- 维持 `Tab`、`Shift+Tab`、`1-9`、`0` 等频道操作手感

#### `widgets/*`
- `video_list.py`：列表选择、鼠标点击、键盘移动与后续 textual-image 接口预留
- `audio_bar.py`：全局底部控制栏，后续接现有播放状态
- `comment_view.py`：右侧评论预览容器

### 3. 现有逻辑的 future-core 复用面

后续 `core/` 抽离建议优先级：

1. **模型与纯函数**
   - `VideoItem` / `CommentItem` / `AudioStream` / `AudioPlaybackState`
   - `human_count()` / `format_timestamp()` / `wrap_display()` / `build_detail_lines()`
2. **状态存储**
   - `HistoryStore`
3. **API**
   - `BilibiliClient`
4. **音频**
   - `play_audio_for_item()` / `toggle_audio_playback()` / `stop_audio_playback()` 等

### 4. 键位对齐原则

阶段 1 已在 Textual App 层保留这些键位语义：

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

### 5. 阶段 2 进入条件

满足以下条件后再进入阶段 2：

- `python -m bili_terminal.tui.app` 能稳定启动
- smoke tests 通过
- HomeScreen 结构、键位和模式切换壳层稳定
- 不再继续扩张阶段 1 的占位逻辑

## macOS 打包影响点（阶段 1 只记录）

当前 `build_macos_app.sh` 只复制：

- `__init__.py`
- `__main__.py`
- `bilibili_cli.py`
- `macos/` helper

当 Textual 版准备进入默认入口时，需要补：

- 整个 `bili_terminal/tui/`
- `styles/bili_dark.tcss`
- Textual / textual-image 依赖环境

## 当前结论

阶段 1 的正确策略不是“立刻把 curses 全部翻译成 Textual”，而是：

1. 先建立新 UI 包结构
2. 先把键位和页面骨架迁过去
3. 再逐步把 `core/` 抽出来接真实数据流
