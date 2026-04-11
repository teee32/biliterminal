# BiliTerminal Textual 重构阶段 1 架构说明

> 目标：在**不破坏现有 CLI / curses TUI** 的前提下，为 `bili_terminal/tui/app.py` 落下可运行骨架，并把 `bili_terminal/bilibili_cli.py` 中后续可抽离的核心能力先梳理清楚。

## 阶段 1 范围

### 目标

- 新增 `bili_terminal/tui/` 包，提供可启动的 Textual `App` 骨架。
- 保持当前命令行入口、`python -m bili_terminal tui` 和 `./bili_terminal/start.sh` 继续可用。
- 明确后续 `core/` 抽离的边界，避免直接把 `bilibili_cli.py` 原样复制进 Textual 层。
- 先保留键位语义与视图结构，不在阶段 1 迁移业务逻辑。

### 非目标

- 本阶段不要求完成 curses TUI 到 Textual 的全量功能平移。
- 本阶段不拆分 Bilibili API 逻辑到多个业务模块。
- 本阶段不改变收藏、历史、音频播放、评论加载等现有行为。
- 本阶段不替换 macOS 打包链路，只记录 Textual 引入后的影响点。

## 建议目录结构

```text
bili_terminal/
├── __init__.py
├── __main__.py
├── bilibili_cli.py              # 现有入口与业务实现，阶段 1 保持可运行
├── tui/
│   ├── __init__.py
│   ├── app.py                   # Textual 入口，提供 BiliTerminalApp / run
│   ├── app.tcss                 # 全局样式
│   ├── screens/
│   │   ├── __init__.py
│   │   └── home.py              # HomeScreen，承接首页布局与快捷键
│   └── widgets/
│       ├── __init__.py
│       ├── hero.py              # 顶部 Hero / 搜索提示
│       ├── sections.py          # 首页分区 tabs / chips
│       ├── video_grid.py        # 占位卡片网格
│       └── detail_panel.py      # 右侧详情 / 评论占位区
├── tests/
│   ├── test_bilibili_cli.py
│   └── test_textual_app.py      # 阶段 1 smoke tests
└── build_macos_app.sh
```

阶段 1 可以只先落下 `app.py`、`app.tcss`、`screens/home.py` 与少量 placeholder widgets；`core/` 建议等阶段 2 再建立，避免一边建骨架一边做大规模拆分。

## 现有代码可复用能力清单

`bili_terminal/bilibili_cli.py` 当前同时承担数据模型、API、状态管理、CLI、curses TUI 五类职责。后续迁移时建议按下面的“复用面”来拆，而不是按 UI 页面硬切。

### 1. 数据模型 / 纯函数工具（适合最先抽到 `core/`）

这些能力几乎不依赖 I/O，最适合先抽：

- 数据对象：`VideoItem`、`CommentItem`、`AudioStream`、`AudioPlaybackState`
- 展示辅助：`human_count()`、`format_timestamp()`、`normalize_duration()`
- 文本布局：`display_width()`、`truncate_display()`、`wrap_display()`
- 视频引用：`parse_video_ref()`、`build_video_url()`、`build_watch_url()`
- 评论/详情转换：`comments_from_payload()`、`comments_from_thread_payload()`、`build_detail_lines()`

建议目标目录：

```text
bili_terminal/core/
├── models.py
├── formatting.py
├── video_refs.py
└── comments.py
```

### 2. 状态存储（历史 / 收藏 / 最近搜索）

`HistoryStore` 已经是单独对象，边界最清晰，可保持 API 基本不变后迁出：

- `add_keyword()`
- `add_video()`
- `add_favorite()` / `remove_favorite()` / `toggle_favorite()`
- `get_recent_keywords()` / `get_recent_videos()` / `get_favorite_videos()`

迁移建议：

- 阶段 1 继续直接复用 `HistoryStore`。
- 阶段 2 再迁到 `bili_terminal/core/history.py`。
- Textual 和 legacy curses 都只依赖同一份 store，避免出现双写状态。

### 3. 音频控制

音频链路耦合度较高，但也已经有相对完整的 API 面：

- 流解析：`extract_audio_stream()`、`play_audio_for_item()`
- 控制：`pause_audio_playback()`、`resume_audio_playback()`、`toggle_audio_playback()`、`stop_audio_playback()`
- 持久化：`save_audio_playback_state()`、`load_audio_playback_state()`、`clear_audio_playback_state()`
- macOS helper：`compile_macos_audio_helper()`、`macos_audio_helper_path()`

迁移建议：

- 阶段 1 不改音频逻辑，只在 Textual action 中调用现有函数。
- 阶段 2 再抽到 `core/audio.py`，并把状态文件路径约束集中管理。

### 4. API 访问层

`BilibiliClient` 已经接近未来 `core/api.py` 的雏形，建议保持类接口不变：

- 首页内容：`popular()`、`recommend()`、`precious()`、`region_ranking()`
- 搜索：`search()`、`search_default()`、`trending_keywords()`
- 详情与评论：`video()`、`comments()`
- 音频：`audio_stream_for_item()`、`audio_stream()`
- 番剧：`bangumi()`、`_bangumi_playinfo()`

迁移建议：

- 阶段 1 不要在 Textual widgets 里直接写请求代码。
- 统一让 Screen / Controller 调用 `BilibiliClient`，保持 I/O 入口单一。
- 后续若要 async 化，再单独处理，不要在本阶段把整个客户端改成异步版本。

### 5. 现有 curses TUI 中值得保留的交互约束

`BilibiliTUI` 虽然体积较大，但已经定义了首页体验与键位语义。Textual 版阶段 1 应至少保留这些意图：

| 意图 | 现有键位 | 阶段 1 Textual 建议 |
| --- | --- | --- |
| 上下移动 | `j/k`, `↑/↓` | 保持一致 |
| 打开详情 | `Enter` | 保持一致 |
| 返回 | `Esc`, `b` | 保持一致 |
| 搜索 | `/`, `s` | 保持一致 |
| 首页分区切换 | `Tab`, `Shift+Tab`, `1-9`, `0` | 保持一致 |
| 历史 / 收藏 | `v`, `m` | 保持一致 |
| 收藏切换 | `f` | 保持一致 |
| 音频播放控制 | `a`, `x` | 保持一致 |
| 刷新 / 评论刷新 | `r`, `c` | 保持一致 |
| 退出 | `q` | 保持一致 |

## Textual 阶段 1 结构建议

### `bili_terminal/tui/app.py`

职责：

- 定义 `BiliTerminalApp(App)`
- 注册 CSS 路径与主屏 `HomeScreen`
- 注入 `BilibiliClient` / `HistoryStore`
- 暴露 `run_textual_app()` 或等价入口，便于未来从 `__main__` / CLI 参数切换

建议保持：

- 可以直接 `python -m bili_terminal.tui.app` 启动
- 不要求接入真实 API 数据也能成功启动（placeholder-first）
- 不直接导入 curses 相关实现

### `HomeScreen`

阶段 1 只要求承载布局与动作定义，不要求完整数据绑定：

- 顶部：标题、默认搜索词占位、热搜占位
- 中间：频道 tabs / chips
- 主体：featured card + grid placeholder
- 右侧/下方：detail / comments placeholder
- 底部：快捷键提示 + 状态栏

### Widgets

建议 widgets 只做表现层：

- 输入：接收简单 dataclass / dict
- 输出：渲染占位或静态文案
- 不直接操作 `HistoryStore` / `BilibiliClient`

这样后续替换占位数据为真实数据时，不需要重写组件结构。

## CLI / 兼容入口建议

阶段 1 推荐保持两条路径并存：

1. **默认稳定路径**：继续使用当前 `tui`（curses）
2. **新路径**：增加 Textual 启动入口，并保留显式 fallback

建议的后续 CLI 形态：

```bash
python -m bili_terminal tui --legacy-tui   # 强制旧版 curses
python -m bili_terminal tui                 # 后续默认可切到 Textual
python -m bili_terminal.tui.app            # 直接调试 Textual 骨架
```

阶段 1 先把 `--legacy-tui` 记录进文档和测试计划即可；真正切换默认入口建议放到阶段 2/3。

## 测试与依赖建议

### 依赖声明

仓库当前没有 `pyproject.toml` / `requirements.txt`。阶段 1 建议补一个最小依赖声明，至少覆盖：

- `textual>=0.30,<1`

如果暂时不引入 `textual-image`，文档里应明确：图片能力不在阶段 1 范围内。

### smoke tests

至少需要两类：

1. `import bili_terminal.tui.app` 不报错
2. `BiliTerminalApp()` 可实例化，且主屏可 compose

如果测试环境已安装 Textual，可额外加入：

- `app.run_test()` 能进入/退出主循环

## macOS 打包影响点

当前 `build_macos_app.sh` 只复制纯 Python 文件与音频 helper。引入 Textual 后需要关注：

- 打包产物中必须带上 `bili_terminal/tui/` 整个包及 `app.tcss`
- 若未来改为 Textual 默认入口，`__main__.py` 或启动命令需要同步更新
- 如果最终使用 `textual-image` 或其他富依赖，需要重新检查目标机器上的 Python 环境与 wheel 可用性
- 现阶段不要改动音频 helper 编译流程，先保证 Textual 资源能被包含

## 建议迁移顺序

### 阶段 1：骨架落地

- 新建 `bili_terminal/tui/` 包
- 跑通 `app.py`、`HomeScreen`、placeholder widgets、CSS
- 增加 Textual smoke tests
- 文档确认目录结构、键位语义、legacy fallback

### 阶段 2：抽出复用核心

- 抽离 `models / formatting / history / api / audio`
- 让 curses TUI 与 Textual 共用同一套核心层
- 保持 CLI 行为不变

### 阶段 3：功能迁移

- 依次迁移首页、搜索、详情、收藏、历史、评论、音频控制
- 用 Textual actions 对齐现有快捷键
- 当功能完整且稳定后，再考虑让 `tui` 默认指向 Textual

## 代码审查结论（阶段 1 视角）

- `HistoryStore`、`BilibiliClient` 已经具备“后续抽 core”的天然边界，适合优先复用。
- `BilibiliTUI` 过于集中，但它把首页布局、视图模式和快捷键语义定义得很完整，适合作为 Textual 首页的行为蓝图。
- 阶段 1 最重要的是**先建立包结构与可启动入口**，而不是抢先做大规模逻辑拆分。
- 为降低团队冲突，优先新增 `tui/`、文档、测试与依赖声明；对 `bilibili_cli.py` 只做最小兼容性接缝改动。
