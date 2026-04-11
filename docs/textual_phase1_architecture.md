# Textual migration — phase 1 architecture snapshot

## Goal

Phase 1 only establishes a runnable `bili_terminal.tui.app` shell, a stable directory target, and a clear extraction map from `bili_terminal/bilibili_cli.py` into future `core/` modules. Existing CLI, REPL, and curses TUI stay unchanged.

## Target directory tree

```text
bili_terminal/
├── __main__.py                    # current CLI entry; remains legacy-compatible
├── bilibili_cli.py                # current single-file implementation (source of truth during phase 1)
├── core/                         # phase 2+ extraction target
│   ├── __init__.py
│   ├── api.py                    # BilibiliClient request / parsing surface
│   ├── audio.py                  # audio worker, player selection, playback state
│   ├── history.py                # HistoryStore + favorites/history persistence
│   ├── models.py                 # VideoItem, CommentItem, AudioStream, ListState
│   └── services.py               # home feed / search / comments orchestration
├── tui/
│   ├── __init__.py
│   ├── app.py                    # new Textual app shell added in phase 1
│   ├── screens.py                # HomeScreen placeholder layout added in phase 1
│   ├── widgets.py                # placeholder panels / keymap legend added in phase 1
│   └── styles.tcss               # packaged Textual styles added in phase 1
└── tests/
    ├── test_bilibili_cli.py
    └── test_textual_app.py       # phase 1 smoke coverage added here
```

## Reusable extraction map from `bilibili_cli.py`

### Models that can move with near-zero behavior risk

- `VideoItem`
- `CommentItem`
- `AudioStream`
- `AudioPlaybackState`
- `ListState`

These are plain dataclasses and can move into `core/models.py` with minimal import shims.

### API surface that should become `core/api.py`

Current public fetch/query methods on `BilibiliClient`:

- `popular()`
- `recommend()`
- `precious()`
- `region_ranking()`
- `bangumi()`
- `search()`
- `video()`
- `audio_stream_for_item()` / `audio_stream()`
- `search_default()`
- `trending_keywords()`
- `comments()`

Supporting internals that should move with the client:

- `_request_text()` / `_request_json()` / `_warmup()` / `_build_headers()`
- `_video_page_state()` / `_video_playinfo()`
- `_comment_wbi_script_keys()` / `_comments_via_wbi()`

### History / favorites / local state surface for `core/history.py`

- `default_state_dir()` / `default_history_path()`
- `HistoryStore.load()` / `save()`
- `HistoryStore.add_keyword()`
- `HistoryStore.add_video()`
- `HistoryStore.add_favorite()` / `remove_favorite()` / `toggle_favorite()`
- `HistoryStore.get_recent_keywords()` / `get_recent_videos()` / `get_favorite_videos()`
- payload helpers such as `item_to_history_payload()`, `video_key_from_item()`, `video_key_from_payload()`

### Audio surface for `core/audio.py`

- `build_audio_player_command()`
- `play_audio_stream()` / `play_audio_for_item()` / `audio_action_for_item()`
- `spawn_audio_worker()` / `run_audio_worker()`
- `save_audio_playback_state()` / `load_audio_playback_state()` / `clear_audio_playback_state()`
- `pause_audio_playback()` / `resume_audio_playback()` / `toggle_audio_playback()` / `stop_audio_playback()`
- macOS helper paths + compile/cache helpers

### UI helpers worth reusing during the migration

- `HOME_CHANNELS`
- `channel_shortcut_index_from_key()`
- `build_detail_lines()`
- `comments_from_payload()`
- `open_video_target()` / `build_watch_url()`

These can remain imported from the legacy module until the new `core/` package exists.

## Stage-1 Textual responsibilities

Implemented now:

- `BiliTerminalTextualApp` shell with preserved keymap intent
- `HomeScreen` placeholder layout using `HOME_CHANNELS`
- placeholder panels for featured content, shelf/list area, and detail/comments area
- packaged `styles.tcss`
- optional `textual` dependency declaration via `pyproject.toml`
- smoke tests for import + headless boot when the extra dependency is installed

Explicitly deferred:

- network-backed data loading in Textual
- extraction of business logic from `bilibili_cli.py`
- real search input flow, detail screen routing, async workers, pagination state, or audio transport changes
- replacement of the current `tui` command

## Preserved keymap intent

The new shell keeps these behaviors reserved so the future Textual migration can stay muscle-memory compatible with the curses TUI:

- `Tab` / `Shift+Tab`: cycle home channels
- `1-9` / `0`: direct channel selection
- `/` or `s`: search
- `Enter`: detail view
- `b` / `h`: back/home
- `v`: history
- `m`: favorites
- `a` / `x`: audio toggle / stop
- `f`: favorite toggle
- `c`: comments refresh
- `r`: refresh
- `l`: rerun last search
- `d`: default search
- `q`: quit

## Detailed phase-1 plan

1. **Freeze behavior**
   - leave `python -m bili_terminal tui` and `./biliterminal` untouched
   - keep `bilibili_cli.py` as the runtime source of truth
2. **Land Textual shell beside legacy paths**
   - new `bili_terminal/tui/` package
   - runnable via `python3 -m bili_terminal.tui.app`
   - no command-routing changes yet
3. **Declare optional dependency**
   - use `pip install -e .[textual]` to opt into the new shell
   - legacy CLI remains stdlib-only
4. **Document extraction boundaries**
   - treat client/history/audio/model helpers above as the first split targets
   - keep import shims from legacy module until extraction is complete
5. **Phase 2 follow-up**
   - create `core/models.py`, `core/history.py`, `core/api.py`, `core/audio.py`
   - swap the Textual shell from placeholder text to real service calls
   - add a `--legacy-tui` flag when the Textual UI becomes the default launch path
6. **Phase 3 follow-up**
   - wire detail screen routing, background loading, and richer navigation
   - update packaging/build flow once the new TUI becomes a shipped entry point

## `--legacy-tui` note

Do **not** add `--legacy-tui` in phase 1. The current default entry is already the legacy CLI/curses surface. Introduce `--legacy-tui` only when a future top-level `tui` command or default launcher begins pointing at Textual.

## macOS packaging impact note

Current `bili_terminal/build_macos_app.sh` copies only:

- `__init__.py`
- `__main__.py`
- `bilibili_cli.py`
- `macos/` helper sources

When Textual becomes part of the shipped app, packaging must also copy the whole `bili_terminal/tui/` package and include `styles.tcss` as package data. Until then, the new shell is intentionally source-only and opt-in.
