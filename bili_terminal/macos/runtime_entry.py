from __future__ import annotations

import sys

from bili_terminal.__main__ import main


def run() -> int:
    args = sys.argv[1:] or ["--tui"]
    return main(args)


if __name__ == "__main__":
    raise SystemExit(run())
