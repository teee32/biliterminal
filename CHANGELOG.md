# Changelog

## v0.3.1 — 2026-05-22

### Fixed
- `Shift+W` 切换稍后看的快捷键之前完全没反应。终端不会为字母键发独立的 shift modifier，所以 Textual 8.x 里 `shift+w` 这种绑定从不触发。绑定改为 `W`，用户文档里的 `Shift+W` 物理描述保持不变。

### Changed
- Claude 主题重新对齐 `claude.ai` 的暖米色调，去掉之前刺眼的纯白卡片，改为三档暖米堆叠：`#f0ede4` 底色 / `#f5f2ea` 卡片 / `#e6e2d6` 顶底栏。
- 强调色从陶土红 `#c15f3c` 调成 Anthropic 橙棕 `#c96442`，Header/Footer 不再用深棕色块。
- 为 dark / light / claude 三个主题分别上色滚动条、Tooltip、LoadingIndicator——之前这些元素都用 Textual 默认深蓝灰，切到亮色主题时会突兀地露出来。

## v0.3.0

详见 git history（首个 Textual-only 发布版本）。
