#!/usr/bin/env python3
"""Generate README screenshots from the live TUI via tmux."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
import unicodedata
from dataclasses import dataclass, replace
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
ASSETS_DIR = ROOT / "assets" / "readme"
APP_BOOT_COMMAND = "python3 -m bili_terminal --tui"

ANSI_RE = re.compile(r"\x1b\[([0-9;]*)m")

FONT_MONO = "/System/Library/Fonts/Menlo.ttc"
FONT_CJK = "/System/Library/Fonts/Hiragino Sans GB.ttc"
FONT_SYMBOL = "/System/Library/Fonts/Apple Symbols.ttf"
FONT_EMOJI = "/System/Library/Fonts/Apple Color Emoji.ttc"

WINDOW_BG = "#0B0C0F"
WINDOW_FILL = "#1A1C21"
TITLE_BAR = "#20232A"
TITLE_TEXT = "#A5A9B4"
TERMINAL_BG = "#1F2024"
TERMINAL_FG = "#ECECEE"
TERMINAL_DIM = "#787E8D"
ACCENT = "#FB7299"

CELL_WIDTH = 15
LINE_HEIGHT = 30
FONT_SIZE = 24
TITLE_SIZE = 22
PADDING_X = 28
PADDING_Y = 24
TITLE_BAR_HEIGHT = 52
SHADOW_OFFSET = 18
CORNER_RADIUS = 24


@dataclass(frozen=True)
class Style:
    fg: str = TERMINAL_FG
    bg: str | None = None
    bold: bool = False
    dim: bool = False


@dataclass(frozen=True)
class Action:
    kind: str
    value: str
    delay: float


@dataclass(frozen=True)
class Scenario:
    name: str
    session: str
    width: int
    height: int
    output: Path
    title: str
    actions: tuple[Action, ...] = ()
    initial_delay: float = 4.0


SCENARIOS = {
    "home": Scenario(
        name="home",
        session="bili_readme_home",
        width=111,
        height=38,
        output=ASSETS_DIR / "tui-home.png",
        title="首页流",
    ),
    "search": Scenario(
        name="search",
        session="bili_readme_search",
        width=120,
        height=34,
        output=ASSETS_DIR / "tui-search.png",
        title="搜索与评论",
        actions=(
            Action("key", "/", 0.35),
            Action("text", "中文", 0.25),
            Action("key", "Enter", 4.0),
            Action("key", "c", 3.0),
        ),
    ),
    "detail": Scenario(
        name="detail",
        session="bili_readme_detail",
        width=110,
        height=30,
        output=ASSETS_DIR / "tui-detail.png",
        title="详情页",
        actions=(
            Action("key", "Enter", 4.0),
        ),
    ),
}


BASE_PALETTE = {
    30: "#1F2024",
    31: "#E16A8A",
    32: "#8CCF9A",
    33: "#E3C56E",
    34: "#83B2FF",
    35: ACCENT,
    36: "#6FD7E7",
    37: TERMINAL_FG,
    90: "#585D68",
    91: "#F28CA5",
    92: "#B7F0A5",
    93: "#FFE090",
    94: "#A8C5FF",
    95: ACCENT,
    96: "#8DE3F3",
    97: "#FFFFFF",
}

BACKGROUND_PALETTE = {
    40: "#1F2024",
    41: "#AF415E",
    42: "#4A8B55",
    43: "#927937",
    44: "#355A9A",
    45: "#D85E88",
    46: "#317D84",
    47: "#F1F2F4",
    100: "#585D68",
    101: "#D9688E",
    102: "#6FB77A",
    103: "#D9B45C",
    104: "#648FD6",
    105: ACCENT,
    106: "#53B3BF",
    107: "#FFFFFF",
}


def run_tmux(*args: str, capture: bool = False) -> str:
    result = subprocess.run(
        ["tmux", *args],
        cwd=ROOT,
        check=True,
        text=True,
        encoding="utf-8",
        capture_output=capture,
    )
    return result.stdout if capture else ""


def try_kill_session(session: str) -> None:
    subprocess.run(
        ["tmux", "kill-session", "-t", session],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )


def capture_scenario(scenario: Scenario) -> str:
    try_kill_session(scenario.session)
    command = f"cd {ROOT} && {APP_BOOT_COMMAND}"
    run_tmux(
        "new-session",
        "-d",
        "-s",
        scenario.session,
        "-x",
        str(scenario.width),
        "-y",
        str(scenario.height),
        command,
    )
    try:
        time.sleep(scenario.initial_delay)
        for action in scenario.actions:
            if action.kind == "key":
                run_tmux("send-keys", "-t", scenario.session, action.value)
            elif action.kind == "text":
                run_tmux("send-keys", "-l", "-t", scenario.session, action.value)
            else:
                raise ValueError(f"Unsupported action kind: {action.kind}")
            time.sleep(action.delay)
        return run_tmux("capture-pane", "-p", "-e", "-t", scenario.session, capture=True)
    finally:
        try_kill_session(scenario.session)


def clamp_color(value: int) -> int:
    return max(0, min(255, value))


def hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    return "#%02x%02x%02x" % rgb


def dim_color(color: str) -> str:
    red, green, blue = hex_to_rgb(color)
    mixed = (
        clamp_color(int(red * 0.58 + 28)),
        clamp_color(int(green * 0.58 + 30)),
        clamp_color(int(blue * 0.58 + 35)),
    )
    return rgb_to_hex(mixed)


def apply_sgr(style: Style, params: str) -> Style:
    if not params:
        return Style()

    values = [int(part) if part else 0 for part in params.split(";")]
    index = 0
    current = style

    while index < len(values):
        code = values[index]
        if code == 0:
            current = Style()
        elif code == 1:
            current = replace(current, bold=True, dim=False)
        elif code == 2:
            current = replace(current, dim=True, bold=False)
        elif code == 22:
            current = replace(current, bold=False, dim=False)
        elif code == 39:
            current = replace(current, fg=TERMINAL_FG)
        elif code == 49:
            current = replace(current, bg=None)
        elif code in BASE_PALETTE:
            current = replace(current, fg=BASE_PALETTE[code])
        elif code in BACKGROUND_PALETTE:
            current = replace(current, bg=BACKGROUND_PALETTE[code])
        elif code in (38, 48):
            is_foreground = code == 38
            if index + 1 < len(values) and values[index + 1] == 2 and index + 4 < len(values):
                color = rgb_to_hex((values[index + 2], values[index + 3], values[index + 4]))
                current = replace(current, fg=color) if is_foreground else replace(current, bg=color)
                index += 4
            elif index + 1 < len(values) and values[index + 1] == 5 and index + 2 < len(values):
                cube = values[index + 2]
                mapped = ansi_256_to_hex(cube)
                current = replace(current, fg=mapped) if is_foreground else replace(current, bg=mapped)
                index += 2
        index += 1

    if current.dim:
        current = replace(current, fg=dim_color(current.fg))
    return current


def ansi_256_to_hex(code: int) -> str:
    if code < 16:
        palette = {
            0: "#1F2024",
            1: "#E16A8A",
            2: "#8CCF9A",
            3: "#E3C56E",
            4: "#83B2FF",
            5: ACCENT,
            6: "#6FD7E7",
            7: "#ECECEE",
            8: "#585D68",
            9: "#F28CA5",
            10: "#B7F0A5",
            11: "#FFE090",
            12: "#A8C5FF",
            13: "#FF9FBC",
            14: "#8DE3F3",
            15: "#FFFFFF",
        }
        return palette.get(code, TERMINAL_FG)
    if 16 <= code <= 231:
        code -= 16
        red = code // 36
        green = (code % 36) // 6
        blue = code % 6
        steps = [0, 95, 135, 175, 215, 255]
        return rgb_to_hex((steps[red], steps[green], steps[blue]))
    gray = 8 + (code - 232) * 10
    return rgb_to_hex((gray, gray, gray))


def char_width(char: str) -> int:
    if char in ("\u200d", "\ufe0f") or unicodedata.combining(char):
        return 0
    if unicodedata.category(char) == "Cf":
        return 0
    return 2 if unicodedata.east_asian_width(char) in {"F", "W"} else 1


def split_clusters(text: str) -> list[tuple[str, int]]:
    clusters: list[tuple[str, int]] = []
    current = ""
    current_width = 0

    for char in text:
        width = char_width(char)
        if not current:
            current = char
            current_width = width or 1
            continue
        if width == 0 or current.endswith("\u200d"):
            current += char
            continue
        clusters.append((current, current_width))
        current = char
        current_width = width or 1

    if current:
        clusters.append((current, current_width))
    return clusters


def parse_ansi(raw: str) -> tuple[list[list[tuple[str, Style, int, int]]], int]:
    rows: list[list[tuple[str, Style, int, int]]] = [[]]
    style = Style()
    column = 0
    max_columns = 0
    index = 0

    while index < len(raw):
        char = raw[index]
        if char == "\x1b":
            match = ANSI_RE.match(raw, index)
            if match:
                style = apply_sgr(style, match.group(1))
                index = match.end()
                continue
        if char == "\n":
            max_columns = max(max_columns, column)
            rows.append([])
            column = 0
            index += 1
            continue
        if char == "\r":
            column = 0
            index += 1
            continue
        width = char_width(char)
        if width == 0:
            if rows[-1]:
                last_text, last_style, last_column, last_width = rows[-1][-1]
                rows[-1][-1] = (last_text + char, last_style, last_column, last_width)
            index += 1
            continue
        rows[-1].append((char, style, column, width))
        column += width
        index += 1

    max_columns = max(max_columns, column)
    while rows and not rows[-1]:
        rows.pop()
    return rows, max_columns


def is_cjk(char: str) -> bool:
    return unicodedata.east_asian_width(char) in {"F", "W"} and not is_box_drawing(char)


def is_box_drawing(char: str) -> bool:
    codepoint = ord(char)
    return 0x2500 <= codepoint <= 0x257F


def is_symbol(char: str) -> bool:
    if is_box_drawing(char) or char.isspace():
        return False
    codepoint = ord(char)
    if is_emoji(char):
        return False
    category = unicodedata.category(char)
    if category in {"So", "Sk"}:
        return True
    return 0x2600 <= codepoint <= 0x27BF


def is_emoji(char: str) -> bool:
    codepoint = ord(char)
    return (
        0x1F000 <= codepoint <= 0x1FAFF
        or 0x2B00 <= codepoint <= 0x2BFF
        or codepoint in {0x2600, 0x2601, 0x2605, 0x2606, 0x2705}
    )


def pick_font(text: str, fonts: dict[str, ImageFont.FreeTypeFont]) -> ImageFont.FreeTypeFont:
    if any(is_emoji(char) for char in text):
        return fonts["emoji"]
    if any(is_symbol(char) for char in text):
        return fonts["symbol"]
    if any(is_cjk(char) for char in text):
        return fonts["cjk"]
    return fonts["mono"]


def load_fonts() -> dict[str, ImageFont.FreeTypeFont]:
    return {
        "mono": ImageFont.truetype(FONT_MONO, FONT_SIZE),
        "cjk": ImageFont.truetype(FONT_CJK, FONT_SIZE),
        "symbol": ImageFont.truetype(FONT_SYMBOL, FONT_SIZE - 1),
        "emoji": ImageFont.truetype(FONT_EMOJI, 26),
        "title": ImageFont.truetype(FONT_CJK, TITLE_SIZE),
    }


def render_capture(scenario: Scenario, raw: str) -> Image.Image:
    rows, columns = parse_ansi(raw)
    if not rows:
        raise RuntimeError(f"No content captured for {scenario.name}")

    fonts = load_fonts()
    content_width = columns * CELL_WIDTH
    content_height = len(rows) * LINE_HEIGHT

    window_width = content_width + PADDING_X * 2
    window_height = content_height + PADDING_Y * 2 + TITLE_BAR_HEIGHT
    canvas_width = window_width + SHADOW_OFFSET * 2 + 26
    canvas_height = window_height + SHADOW_OFFSET * 2 + 30

    image = Image.new("RGB", (canvas_width, canvas_height), WINDOW_BG)
    draw = ImageDraw.Draw(image)

    shadow_box = (
        SHADOW_OFFSET,
        SHADOW_OFFSET,
        SHADOW_OFFSET + window_width,
        SHADOW_OFFSET + window_height,
    )
    draw.rounded_rectangle(shadow_box, radius=CORNER_RADIUS, fill="#090A0D")

    window_x = SHADOW_OFFSET - 8
    window_y = SHADOW_OFFSET - 8
    window_box = (window_x, window_y, window_x + window_width, window_y + window_height)
    draw.rounded_rectangle(window_box, radius=CORNER_RADIUS, fill=WINDOW_FILL)

    title_box = (window_x, window_y, window_x + window_width, window_y + TITLE_BAR_HEIGHT)
    draw.rounded_rectangle(title_box, radius=CORNER_RADIUS, fill=TITLE_BAR)
    draw.rectangle(
        (window_x, window_y + TITLE_BAR_HEIGHT - CORNER_RADIUS, window_x + window_width, window_y + TITLE_BAR_HEIGHT),
        fill=TITLE_BAR,
    )

    light_y = window_y + TITLE_BAR_HEIGHT // 2
    light_x = window_x + 24
    for offset, color in enumerate(("#FF5F57", "#FEBC2E", "#28C840")):
        cx = light_x + offset * 26
        draw.ellipse((cx - 7, light_y - 7, cx + 7, light_y + 7), fill=color)

    title_text = f"ggziblaking — biliterminal — Python -m bili_terminal tui — {scenario.width}×{scenario.height}"
    title_font = fonts["title"]
    draw.text((window_x + 92, window_y + 14), title_text, font=title_font, fill=TITLE_TEXT)

    content_x = window_x + PADDING_X
    content_y = window_y + TITLE_BAR_HEIGHT + PADDING_Y
    draw.rounded_rectangle(
        (
            content_x - 10,
            content_y - 10,
            content_x + content_width + 10,
            content_y + content_height + 10,
        ),
        radius=18,
        fill=TERMINAL_BG,
    )

    for row_index, row in enumerate(rows):
        y = content_y + row_index * LINE_HEIGHT
        background_runs: list[tuple[str, int, int]] = []
        pending_bg: tuple[str, int, int] | None = None

        for _, style, column, width in row:
            if not style.bg:
                if pending_bg:
                    background_runs.append(pending_bg)
                    pending_bg = None
                continue
            x = content_x + column * CELL_WIDTH
            run_end = x + width * CELL_WIDTH
            if pending_bg and pending_bg[0] == style.bg and pending_bg[2] == x:
                pending_bg = (style.bg, pending_bg[1], run_end)
            else:
                if pending_bg:
                    background_runs.append(pending_bg)
                pending_bg = (style.bg, x, run_end)

        if pending_bg:
            background_runs.append(pending_bg)

        for color, x1, x2 in background_runs:
            draw.rectangle((x1, y + 4, x2, y + LINE_HEIGHT - 4), fill=color)

        for text, style, column, _ in row:
            x = content_x + column * CELL_WIDTH
            cluster_font = pick_font(text, fonts)
            text_y = y - 1
            if cluster_font == fonts["emoji"]:
                text_y = y + 1
            elif cluster_font == fonts["symbol"]:
                text_y = y + 1
            elif cluster_font == fonts["cjk"]:
                text_y = y - 2
            draw_kwargs = {}
            if cluster_font == fonts["emoji"]:
                draw_kwargs["embedded_color"] = True
            else:
                draw_kwargs["fill"] = style.fg
            draw.text((x, text_y), text, font=cluster_font, **draw_kwargs)

    return image


def render_and_save(scenario: Scenario) -> None:
    raw = capture_scenario(scenario)
    image = render_capture(scenario, raw)
    scenario.output.parent.mkdir(parents=True, exist_ok=True)
    image.save(scenario.output, optimize=True)
    print(f"Wrote {scenario.output.relative_to(ROOT)}")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "scenarios",
        nargs="*",
        choices=sorted(SCENARIOS),
        help="Subset of screenshots to generate. Defaults to all.",
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    selected = args.scenarios or list(SCENARIOS)
    for name in selected:
        render_and_save(SCENARIOS[name])
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
