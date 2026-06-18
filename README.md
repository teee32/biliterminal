# BiliTerminal

一个轻量、低打扰、适合在终端里摸鱼刷一眼的 Bilibili 客户端。

适合上班空隙快速看首页、搜中文视频、翻评论、顺手先收藏，等有空了再去网页端继续看。

## 快速启动

macOS 双击版：

- 直接下载：<https://github.com/teee32/biliterminal/releases/latest/download/BiliTerminal-macOS.zip>
- 解压后双击 `BiliTerminal.app`

源码启动：

```bash
git clone https://github.com/teee32/biliterminal.git && cd biliterminal && ./biliterminal
```

已经 clone 下来之后：

```bash
./biliterminal
```

如果想直接启动某个命令：

```bash
./biliterminal recommend -n 5
./biliterminal search 中文 -n 5
./biliterminal audio BV19K9uBmEdx
./biliterminal audio pause
./biliterminal audio resume
./biliterminal audio stop
./biliterminal favorite BV19K9uBmEdx
./biliterminal favorites
./biliterminal favorites open 1
./biliterminal comments BV19K9uBmEdx -n 3
```

兼容方式：

```bash
python3 -m bili_terminal tui
./bili_terminal/start.sh
```

自己构建 macOS 双击版：

```bash
./bili_terminal/build_macos_app.sh
open dist/BiliTerminal.app
```

## 界面预览

下面这几张都是当前版本的真实运行截图。

### 首页流

![BiliTerminal 首页流](assets/readme/tui-home.png)

### 搜索与评论

![BiliTerminal 搜索与评论](assets/readme/tui-search.png)

### 详情页

![BiliTerminal 详情页](assets/readme/tui-detail.png)

这个实现基于对 Bilibili 网页公开接口的逆向观察，当前覆盖 3 个核心能力：

- 首页推荐流
- 热门视频列表
- 入站必刷列表
- 关键词搜索
- 首页热搜词
- 视频详情查看
- 视频评论预览
- 从终端直接打开浏览器页面
- 本地收藏夹，支持稍后从浏览器继续看
- 最近搜索与最近浏览历史
- 交互式 REPL，支持基于上一次列表结果按序号继续操作
- 全屏 TUI，支持首页推荐流、分区切换、方向键浏览、回车进入详情页、历史视图、返回栈和帮助浮层
- TUI 搜索框支持直接输入中文关键词

## 运行

项目文件已经集中在 `bili_terminal/` 目录下，直接运行目录内的脚本即可。

```bash
python3 bili_terminal/bilibili_cli.py hot -n 5
python3 bili_terminal/bilibili_cli.py recommend -n 5
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
python3 -m bili_terminal tui
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

当前双击版仍需要目标机器能找到 `python3`。启动日志会写到 `~/.biliterminal/launcher.log`。

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

- `↑/↓` 或 `j/k`：移动选中项（停留片刻自动加载热评）
- `Enter`：进入全屏详情视图
- `Esc` 或 `b`：从详情页返回，或回到上一个列表状态
- `/` 或 `s`：输入搜索关键词
- `Tab` / `Shift+Tab`：切换首页分区
- `1-9`：直接切到首页对应分区
- 直接输入中文即可搜索，例如 `原神`、`中文`
- `l`：重新执行最近一次搜索
- `d`：使用首页默认搜索词直接搜索
- `h`：切回首页内容流
- `v`：切到最近浏览
- `m`：切到收藏夹
- `V`：播放当前视频的 ASCII 终端画面（视频模式中 `q/Esc/b/V` 返回 TUI，`Space` 暂停/继续，`x` 停止）
- `f`：收藏 / 取消收藏当前视频
- `a`：播放 / 暂停当前视频音频
- `x`：停止当前音频
- `n/p`：翻页
- `PgUp/PgDn`：在详情页滚动
- `o`：浏览器打开当前视频
- `c`：刷新当前视频评论预览
- `r`：刷新当前列表
- `?`：显示帮助浮层
- `q`：退出

## 测试

```bash
python3 -m pytest bili_terminal/tests -v
# 或者用标准库:
python3 -m unittest discover -s bili_terminal/tests -v
```

## pip 安装（可选）

```bash
pip install .
biliterminal tui
```

## 登录与账号配置

Bilibili 限制了未登录用户的视频/音频流长度（通常只能播放前几帧或数十秒）。为了获得完整的播放体验，建议进行登录：

### 1. 本地二维码登录（推荐）

在终端中执行：

```bash
./biliterminal login
```

程序会获取 Bilibili 登录链接，并在本地生成二维码页面后自动用浏览器打开。扫码并确认登录后，终端会自动保存登录凭据（`credentials.json`）到本地状态目录（`.omx/state/` 或 `~/.biliterminal/state/`）。二维码在本地生成，不会把登录链接发送给第三方服务。

如果在交互式 REPL 中，也可以直接输入 `login` 启动登录。

### 2. 手动配置 Cookie（无浏览器/服务器环境）

如果你的运行环境没有浏览器，运行 `./biliterminal login` 后，可以直接将你的 Cookie 粘贴到命令行提示中。

你也可以使用以下方式手动配置：

- **环境变量**：
  - `BILITERMINAL_COOKIE`：你的完整 Cookie 字符串
  - `BILITERMINAL_SESSDATA`：仅 `SESSDATA` 值
- **凭据文件**：
  在状态目录（`.omx/state/` 或 `~/.biliterminal/state/`）下创建 `credentials.json`，格式如下：
  ```json
  {
    "cookie": "SESSDATA=xxxx; bili_jct=xxxx; ..."
  }
  ```

## 说明

- CLI 会为接口补齐浏览器请求头，降低被风控 412 的概率。
- 仓库内直接运行时，搜索词和最近浏览视频会落到 `.omx/state/bilibili-cli-history.json`。
- 双击版会把历史写到 `~/.biliterminal/state/bilibili-cli-history.json`，并把启动日志写到 `~/.biliterminal/launcher.log`。
- 音频播放优先使用 `mpv`（通过 IPC 控制暂停），其次是 macOS 原生无窗体 audio helper（直接流式播放，原生暂停），再次是 `ffplay`，最后回退到下载后用 `afplay` 播放。暂停走播放器原生接口，不会出现卡顿重复音。
- TUI 里 `a` 是当前视频的播放 / 暂停切换，`x` 会直接停止当前音频；顶栏会用 `▸ / ⏸` 实时显示正在播放的标题；CLI / REPL 里也支持 `audio pause`、`audio resume`、`audio stop`。
- TUI 边框使用 curses ACS 备用字符集绘制，规避了部分终端（如 Ghostty 默认配置）把歧义宽度字符按双宽渲染导致的框线错位，在各类终端下都能正确对齐。
- 这是一个偏“轻量摸鱼”场景的终端浏览器，不是下载器，支持本地二维码登录和手动配置登录态以获取完整视频流，但没有实现投稿、评论发送、弹幕发送等其他交互写入功能。
- 目前默认聚焦视频内容，不处理直播、课程、专栏、动态等其他内容类型。
- 终端版已经接入首页推荐、热搜、默认搜索词、入站必刷与分区榜单，但因为 curses 终端没有图片和瀑布流组件，所以还不是官网像素级复刻。

## 致谢

本项目受 [LINUX DO](https://linux.do/) 社区启发和支持。
