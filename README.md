# BiliTerminal

一个 **Textual TUI-only** 的终端 Bilibili 客户端。

适合上班空隙快速看首页、刷分区排行、搜中文视频、翻评论、顺手先收藏，等有空了再去网页端继续看。

当前主界面与后续演进方向都围绕 **Textual**，仓库不再暴露旧命令行浏览器或旧终端 UI：

- **Textual v0.3 UI**：首页内容流、搜索、详情页、评论预览、历史、收藏、稍后看、主题切换、帮助浮层
- **macOS `.app` 双击版**：默认直接进入 Textual
- **本地持久化**：历史、收藏、稍后看与主题配置都保存在本机，不自动同步

## 快速启动

默认直接进入 Textual。

macOS 双击版：

- 直接下载：<https://github.com/teee32/biliterminal/releases/latest/download/BiliTerminal-macOS.zip>
- 解压后双击 `BiliTerminal.app`

源码启动 Textual：

```bash
git clone https://github.com/teee32/biliterminal.git && cd biliterminal
python3 -m pip install -e .
./biliterminal
./biliterminal --tui
```

模块入口：

```bash
python3 -m bili_terminal
python3 -m bili_terminal --tui
```

自己构建 macOS 双击版：

```bash
python3 -m pip install -e '.[build]'
./bili_terminal/build_macos_app.sh
open dist/BiliTerminal.app
```

构建依赖（macOS）：

- `pyinstaller`
- `osacompile`
- `ditto`
- `clang`（用于原生音频 helper，缺失时会回退到运行时再尝试编译）

## 界面预览

下面两张都是当前版本的真实运行截图，重点展示 **Textual v0.3**。

### 首页流

![BiliTerminal 首页流](assets/readme/tui-home.png)

### 搜索与评论

![BiliTerminal 搜索与评论](assets/readme/tui-search.png)

## 当前能力

这个实现基于对 Bilibili 网页公开接口的观察与终端交互适配，当前覆盖：

- 首页推荐流
- 热门视频列表
- 入站必刷列表
- 分区排行榜
- 番剧 / 国创 / 影视
- 关键词搜索
- 首页热搜词
- 视频详情查看
- 视频评论预览
- 从终端直接打开浏览器页面
- 本地收藏夹
- 本地稍后看队列：手动加入、手动移出，不自动同步
- 最近搜索与最近浏览历史
- Textual 全屏 UI：支持首页推荐流、分区切换、搜索、详情页、评论预览、历史、收藏、帮助浮层
- Textual 主题切换：`Ctrl+T / F2` 在 dark / light / claude 间循环，并写回 `~/.biliterminal/config.toml`
- 命令面板入口：`Theme` / `Keys`
- TUI 搜索框支持直接输入中文关键词

## 运行

仓库根目录包装脚本、模块入口和安装后的 `biliterminal` 命令共享同一套 Textual 启动语义。

```bash
./biliterminal
./bili_terminal/start.sh
python3 -m bili_terminal
python3 -m unittest discover -s bili_terminal/tests -v
```

## macOS 双击运行

直接下载 release：

- <https://github.com/teee32/biliterminal/releases/latest/download/BiliTerminal-macOS.zip>

自己构建应用包：

```bash
./bili_terminal/build_macos_app.sh
```

构建完成后会生成两个产物：

- `dist/BiliTerminal.app`
- `dist/BiliTerminal-macOS.zip`

本机直接双击 `dist/BiliTerminal.app` 即可，或者命令行执行：

```bash
open dist/BiliTerminal.app
```

如果要发给别人，直接把 `dist/BiliTerminal-macOS.zip` 发过去，解压后双击 `.app`。

当前双击版会优先运行包内置的独立 runtime，**不再要求目标机器额外安装 `python3`**。启动日志会写到 `~/.biliterminal/launcher.log`。

分发注意事项：

- 这是 **macOS 专用** 产物
- 当前 `.app` 只做了 **ad-hoc 签名**，还**没有 Developer ID 签名 / notarization**，在别的 Mac 上第一次打开可能会被 Gatekeeper 拦截
- 当前发行物是**本机架构构建**；如果你要同时覆盖 Intel Mac 和 Apple Silicon，建议分别验证或单独做双架构发布
- 构建脚本现在会在打包后自动做一次 `launch.command --help` 烟测，确认优先走包内 runtime，而不是回退到系统 `python3`

## TUI 快捷键

- `↑/↓` 或 `j/k`：移动选中项
- `Enter`：进入全屏详情视图
- `Esc` 或 `b`：从详情页返回，或回到上一个列表状态
- `/` 或 `s`：输入搜索关键词
- `Tab` / `Shift+Tab`：切换首页分区
- `1-9`：直接切到首页前 9 个分区
- `0`：直接切到第 10 个分区（当前是番剧）
- 直接输入中文即可搜索，例如 `原神`、`中文`
- `l`：重新执行最近一次搜索
- `d`：使用首页默认搜索词直接搜索
- `h`：切回首页内容流
- `v`：切到最近浏览
- `m`：切到收藏夹
- `w`：切到稍后看队列
- `Shift+W`：加入 / 移出稍后看
- `f`：收藏 / 取消收藏当前视频
- `a`：播放 / 暂停当前视频音频
- `x`：停止当前音频
- `Ctrl+T`：深色 / 浅色 / Claude 主题即时切换（并写回 `~/.biliterminal/config.toml`）
- `n/p`：翻页
- `PgUp/PgDn`：在详情页滚动
- `o`：浏览器打开当前视频
- `c`：刷新当前视频评论预览
- `r`：刷新当前列表
- `?`：显示帮助浮层
- `q`：退出

## Textual v0.3.1

v0.3.1 在 v0.3 基础上做了两项打磨：

- Claude 主题重新对齐 `claude.ai` 的暖米色调（三档：`#f0ede4` 底 / `#f5f2ea` 卡片 / `#e6e2d6` 顶底栏），强调色改为 Anthropic 橙棕 `#c96442`；同时为三个主题各自上色滚动条、Tooltip、LoadingIndicator，避免切到亮色主题时露出深色默认样式
- 修复 `Shift+W` 切换稍后看的快捷键无效（终端不会为字母键发独立 shift modifier，绑定从 `shift+w` 改成 `W`，用户文档里的 `Shift+W` 物理描述不变）

当前仓库已经收束为 Textual-only：

- 发布策略：默认 shell、模块入口、安装后命令和 macOS `.app` 都直接启动新版 Textual TUI
- 统一入口：`python3 -m bili_terminal`、仓库根目录 `./biliterminal`、以及 `bili_terminal/start.sh` 共享同一套启动语义
- 安装后入口：`python3 -m pip install -e .` 会注册 `biliterminal` 命令
- 完整 Screen 流：`HomeScreen`、`SearchScreen`、`DetailScreen`、`HistoryScreen`、`FavoritesScreen`、`WatchLaterScreen`
- 统一 Widget：`VideoList`、`CommentView`、`AudioBar`
- 键位语义：`↑/↓ / j/k`、`Enter`、`Esc/b`、`/ / s`、`Tab/Shift+Tab`、`1-9 / 0`、`l`、`d`、`h`、`v`、`m`、`w`、`Shift+W`、`f`、`a`、`x`、`n/p`、`PgUp/PgDn`、`o`、`c`、`r`、`?`、`q`
- 主题菜单与帮助菜单：命令面板 `Ctrl+P` 可直接进入 `Theme` / `Keys`
- 结构说明：[`docs/textual-phase1-architecture.md`](docs/textual-phase1-architecture.md)

启动方式：

```bash
python3 -m bili_terminal
./biliterminal
./bili_terminal/start.sh
```

主题配置（热重载）：

- 配置文件：`~/.biliterminal/config.toml`
- TUI 内可直接按 `Ctrl+T` 在 `dark / light / claude` 间切换，切换后会立刻重载并持久化到配置文件
- 示例：

```toml
[ui]
theme = "claude"  # dark / light / claude
```

## 测试

```bash
python3 -m unittest discover -s bili_terminal/tests -v
```

README 截图可通过下面的脚本重新生成：

```bash
./.venv/bin/python bili_terminal/generate_readme_screenshots.py
```

## 说明

- Core 层会为接口补齐浏览器请求头，降低被风控 412 的概率。
- 仓库内直接运行时，搜索词和最近浏览视频会落到 `.biliterminal/state/biliterminal-history.json`。
- 双击版会把历史写到 `~/.biliterminal/state/biliterminal-history.json`，并把启动日志写到 `~/.biliterminal/launcher.log`。
- 音频播放优先使用 `mpv` 或 `ffplay` 直连；macOS 上如果都没装，会自动走后台下载后用原生无窗体 audio helper 播放，只有 helper 不可用时才回退到 `afplay`。
- TUI 里 `a` 是当前视频的播放 / 暂停切换，`x` 会直接停止当前音频。
- 这是一个偏“轻量摸鱼”场景的终端浏览器，不是下载器，也没有实现登录态、投稿、评论发送、弹幕发送等需要更高权限的功能。
- 目前默认聚焦视频内容，不处理直播、课程、专栏、动态等其他内容类型。
- Textual 版已经接入首页推荐、热搜、默认搜索词、入站必刷与分区榜单，但终端环境没有完整网页图片瀑布流和登录态组件，所以不是官网像素级复刻。

## 致谢

本项目受 [LINUX DO](https://linux.do/) 社区启发和支持。
