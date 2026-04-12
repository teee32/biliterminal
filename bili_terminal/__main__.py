from __future__ import annotations

import sys

from .bilibili_cli import main as legacy_main

TEXTUAL_ENTRYPOINTS = {"textual", "new-tui", "--tui"}
LEGACY_TUI_ENTRYPOINTS = {"legacy-tui", "--legacy-tui"}


def _run_textual(argv: list[str]) -> int:
    from .tui.app import main as textual_main

    original_argv = sys.argv[:]
    try:
        sys.argv = [original_argv[0], *argv]
        return textual_main()
    finally:
        sys.argv = original_argv


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] in TEXTUAL_ENTRYPOINTS:
        return _run_textual(args[1:])
    if args and args[0] in LEGACY_TUI_ENTRYPOINTS:
        return legacy_main(["tui", *args[1:]])
    return legacy_main(args)


if __name__ == "__main__":
    raise SystemExit(main())
