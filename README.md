# BiliTerminal

一个以 **Textual v0.3 UI** 为主的终端 Bilibili 客户端。

适合上班空隙快速看首页、刷分区排行、搜中文视频、翻评论、顺手先收藏，等有空了再去网页端继续看。

当前主界面与后续演进方向都围绕 **Textual**：

- **Textual v0.3 UI**：首页内容流、搜索、详情页、评论预览、历史/收藏、主题切换、帮助浮层
- **macOS `.app` 双击版**：默认直接进入 Textual
- **Windows 免安装版**：解压后双击 `launch.bat` 即可运行
- **legacy curses TUI**：仅作为兼容 fallback 保留，不在 Windows 上支持

## 快速启动

最推荐：直接进入 Textual。

macOS 双击版：

- 直接下载：<https://github.com/teee32/biliterminal/releases/latest/download/BiliTerminal-macOS.zip>
- 解压后双击 `BiliTerminal.app`

源码启动 Textual：

macOS / Linux：

```bash
git clone https://github.com/teee32/biliterminal.git && cd biliterminal
./biliterminal textual
# 或
./biliterminal --tui
```

Windows：

```bat
git clone https://github.com/teee32/biliterminal.git && cd biliterminal
biliterminal.bat textual
:: 或
biliterminal.bat --tui
```

模块入口：

```bash
# macOS / Linux
python3 -m bili_terminal textual
python3 -m bili_terminal --tui

# Windows
python -m bili_terminal textual
python -m bili_terminal --tui
```

兼容 fallback（legacy curses，仅 macOS / Linux）：

```bash
./biliterminal
./biliterminal --legacy-tui
python3 -m bili_terminal tui
python3 -m bili_terminal --legacy-tui
```

直接使用功能命令：

```bash
./biliterminal recommend -n 5
./biliterminal rank music --day 7
./biliterminal bangumi 番剧 --index -n 5
./biliterminal search 中文 -n 5
./biliterminal audio BV19K9uBmEdx
./biliterminal favorite BV19K9uBmEdx
./biliterminal comments BV19K9uBmEdx -n 3
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

自己构建 Windows 免安装版：

```powershell
python -m pip install -e ".[build]"
powershell -ExecutionPolicy Bypass -File .\bili_terminal\windows\build_windows_app.ps1
```

构建完成后会生成：

- `dist\BiliTerminal\` — 免安装目录，双击 `launch.bat` 启动
- `dist\BiliTerminal-Windows.zip` — 压缩包，可分发

构建依赖（Windows）：

- `pyinstaller`
- PowerShell 5.1+（Windows 11 自带）
- 音频播放需要 `ffplay`（FFmpeg 附带，已包含在 PATH 即可）

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
- 分区排行榜：`rank` / `ranking`
- 番剧 / 国创 / 影视：`bangumi`
- 关键词搜索
- 首页热搜词
- 视频详情查看
- 视频评论预览
- 从终端直接打开浏览器页面
- 本地收藏夹，支持稍后从浏览器继续看
- 最近搜索与最近浏览历史
- 交互式 REPL，支持基于上一次列表结果按序号继续操作
- Textual 全屏 UI：支持首页推荐流、分区切换、搜索、详情页、评论预览、历史、收藏、帮助浮层
- Textual 主题切换：`Ctrl+T / F2`，并写回 `~/.biliterminal/config.toml`
- 命令面板入口：`Theme` / `Keys`
- TUI 搜索框支持直接输入中文关键词

## 运行

项目文件已经集中在 `bili_terminal/` 目录下，直接运行目录内的脚本即可。

```bash
# macOS / Linux
python3 bili_terminal/bilibili_cli.py hot -n 5
python3 bili_terminal/bilibili_cli.py recommend -n 5
python3 bili_terminal/bilibili_cli.py rank --rid 3 --day 7
python3 bili_terminal/bilibili_cli.py bangumi 番剧 --index -n 5
python3 bili_terminal/bilibili_cli.py precious -n 5
python3 bili_terminal/bilibili_cli.py trending -n 10
python3 bili_terminal/bilibili_cli.py search 原神 -n 5
python3 bili_terminal/bilibili_cli.py audio BV19K9uBmEdx
python3 bili_terminal/bilibili_cli.py audio pause
python3 bili_terminal/bilibili_cli.py audio resume
python3 bili_terminal/bilibili_cli.py audio stop
python3 bili_terminal/bilibili_cli.py video BV1xx411c7mu
python3 bili_terminal/bilibili_cli.py favorite BV19K9uBmEdx
python3 bili_terminal/bilibili_cli.py favorites
python3 bili_terminal/bilibili_cli.py favorites open 1
python3 bili_terminal/bilibili_cli.py favorites remove 1
python3 bili_terminal/bilibili_cli.py history
python3 bili_terminal/bilibili_cli.py repl
python3 bili_terminal/bilibili_cli.py tui
python3 -m bili_terminal recommend -n 5
python3 -m bili_terminal rank music --day 7
python3 -m bili_terminal bangumi 番剧 --index -n 5
python3 -m bili_terminal textual
python3 -m unittest discover -s bili_terminal/tests -v
```

```bat
:: Windows（大部分命令相同，用 python 替代 python3）
python bili_terminal/bilibili_cli.py hot -n 5
python bili_terminal/bilibili_cli.py audio BV19K9uBmEdx
python bili_terminal/bilibili_cli.py audio pause
python bili_terminal/bilibili_cli.py audio resume
python bili_terminal/bilibili_cli.py audio stop
python -m bili_terminal textual
python -m unittest discover -s bili_terminal/tests -v
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

## Windows 免安装版运行

下载 release：

- <https://github.com/teee32/biliterminal/releases/latest/download/BiliTerminal-Windows.zip>

解压后双击 `launch.bat` 即可启动 Textual UI。

`launch.bat` 会优先使用包内 PyInstaller 打包的 runtime（不需要系统安装 Python），若 runtime 缺失则回退到系统 `python -m bili_terminal --tui`。启动日志写到 `launcher.log`。

音频播放需要 `ffplay`（FFmpeg 附带），请确保 `ffplay` 在 PATH 中。Windows 版不支持 macOS 原生音频 helper 和 `afplay` 回退路径。

## REPL 示例

```text
$ python3 bili_terminal/bilibili_cli.py repl
bili> hot 1 5
bili> audio 1
bili> audio pause
bili> audio stop
bili> favorite 1
bili> favorites
bili> favorites open 1
bili> video 1
bili> open 1
bili> search 原神 1 5
```

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
- `f`：收藏 / 取消收藏当前视频
- `a`：播放 / 暂停当前视频音频
- `x`：停止当前音频
- `Ctrl+T`：深色 / 浅色主题即时切换（并写回 `~/.biliterminal/config.toml`）
- `n/p`：翻页
- `PgUp/PgDn`：在详情页滚动
- `o`：浏览器打开当前视频
- `c`：刷新当前视频评论预览
- `r`：刷新当前列表
- `?`：显示帮助浮层
- `q`：退出

## Textual v0.3.0

当前仓库已经完成 Textual 版主流程，在**不破坏现有 CLI / legacy curses TUI** 的前提下提供：

- 发布策略：默认 shell 启动仍走 legacy curses TUI，`textual` / `new-tui` 显式进入新 UI，`legacy-tui` / `--legacy-tui` 作为强制 fallback 保留
- 统一入口：`python3 -m bili_terminal ...`、仓库根目录 `./biliterminal`、以及 `bili_terminal/start.sh` 共享同一套 launch 语义
- 安装后入口：`python3 -m pip install -e .` 会注册 `biliterminal` 命令，保持与仓库脚本一致的参数行为
- 完整 Screen 流：`HomeScreen`、`SearchScreen`、`DetailScreen`、`HistoryScreen`、`FavoritesScreen`
- 统一 Widget：`VideoList`、`CommentView`、`AudioBar`
- 保留原键位语义：`↑/↓ / j/k`、`Enter`、`Esc/b`、`/ / s`、`Tab/Shift+Tab`、`1-9 / 0`、`l`、`d`、`h`、`v`、`m`、`f`、`a`、`x`、`n/p`、`PgUp/PgDn`、`o`、`c`、`r`、`?`、`q`
- 主题菜单与帮助菜单：命令面板 `Ctrl+P` 可直接进入 `Theme` / `Keys`
- 结构说明：[`docs/textual-phase1-architecture.md`](docs/textual-phase1-architecture.md)
- 兼容约束：现有 `python3 -m bili_terminal tui`、`./bili_terminal/start.sh`、macOS `.app` 打包继续保留
- 入口语义：`tui` 仍然是 legacy curses；`textual` / `new-tui` / `--tui` 才是新版 Textual UI；macOS `.app` 默认双击启动新版 Textual

启动方式：

```bash
python3 -m bili_terminal textual
./biliterminal textual
./bili_terminal/start.sh textual
```

主题配置（热重载）：

- 配置文件：`~/.biliterminal/config.toml`
- TUI 内可直接按 `Ctrl+T` 在 `dark / light` 间切换，切换后会立刻重载并持久化到配置文件
- 示例：

```toml
[ui]
theme = "light"  # dark / light
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

- CLI 会为接口补齐浏览器请求头，降低被风控 412 的概率。
- 仓库内直接运行时，搜索词和最近浏览视频会落到 `.omx/state/bilibili-cli-history.json`。
- 双击版会把历史写到 `~/.biliterminal/state/bilibili-cli-history.json`，并把启动日志写到 `~/.biliterminal/launcher.log`。
- 音频播放优先使用 `mpv` 或 `ffplay` 直连；macOS 上如果都没装，会自动走后台下载后用原生无窗体 audio helper 播放，只有 helper 不可用时才回退到 `afplay`；Windows 上使用 `ffplay`，进程暂停/恢复通过 `NtSuspendProcess`/`NtResumeProcess` 实现（零额外依赖）。
- TUI 里 `a` 是当前视频的播放 / 暂停切换，`x` 会直接停止当前音频；CLI / REPL 里也支持 `audio pause`、`audio resume`、`audio stop`。
- 这是一个偏“轻量摸鱼”场景的终端浏览器，不是下载器，也没有实现登录态、投稿、评论发送、弹幕发送等需要更高权限的功能。
- 目前默认聚焦视频内容，不处理直播、课程、专栏、动态等其他内容类型。
- 终端版已经接入首页推荐、热搜、默认搜索词、入站必刷与分区榜单，但因为 curses 终端没有图片、瀑布流和登录态组件，所以还不是官网像素级复刻。
- Windows 兼容层：POSIX 信号（`SIGSTOP`/`SIGCONT`/`SIGTERM` 等）通过 `platform_audio` 模块按平台分发，Windows 使用 `ctypes` 调用 ntdll.dll，macOS 逻辑完全不变。legacy curses TUI 不支持 Windows。

## 致谢

本项目受 [LINUX DO](https://linux.do/) 社区启发和支持。
