from __future__ import annotations

import sys

TEXTUAL_ENTRYPOINTS = {"textual", "new-tui", "tui", "--tui"}
HELP_ENTRYPOINTS = {"-h", "--help", "help"}
AUDIO_WORKER_ENTRYPOINT = "audio-worker"


def _print_usage() -> None:
    print(
        "usage: BiliTerminal [--tui]\n\n"
        "BiliTerminal now starts the new Textual TUI by default.\n"
        "Aliases kept for convenience: textual, new-tui, tui, --tui.",
        file=sys.stdout,
    )


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
    if args and args[0] == AUDIO_WORKER_ENTRYPOINT:
        from .core import main as core_main

        return core_main(args)
    if args and args[0] in HELP_ENTRYPOINTS:
        _print_usage()
        return 0
    if args and args[0] in TEXTUAL_ENTRYPOINTS:
        if any(arg in HELP_ENTRYPOINTS for arg in args[1:]):
            _print_usage()
            return 0
        return _run_textual(args[1:])
    if args:
        print(
            "BiliTerminal now only exposes the new Textual TUI. "
            "Run `python -m bili_terminal` or `python -m bili_terminal --tui`.",
            file=sys.stderr,
        )
        return 2
    return _run_textual([])


if __name__ == "__main__":
    raise SystemExit(main())
