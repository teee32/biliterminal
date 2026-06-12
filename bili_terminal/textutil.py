from __future__ import annotations

import datetime as dt
import unicodedata
from functools import lru_cache
import re

HTML_TAG_PATTERN = re.compile(r"<[^>]+>")
WHITESPACE_PATTERN = re.compile(r"\s+")
COMMON_MOJIBAKE_CHARS = set("ÃÂÐÑãäåæçèéêëìíîïðñòóôõöùúûüýþÿ")


def strip_html(value: str) -> str:
    return HTML_TAG_PATTERN.sub("", value or "").strip()


def compact_whitespace(value: str) -> str:
    return WHITESPACE_PATTERN.sub(" ", value or "").strip()


def has_cjk(value: str) -> bool:
    return any("一" <= char <= "鿿" for char in value)


def repair_mojibake(value: str) -> str:
    cleaned = compact_whitespace(value)
    if not cleaned or has_cjk(cleaned):
        return cleaned
    if any(ord(char) > 255 for char in cleaned):
        return cleaned
    try:
        repaired = cleaned.encode("latin1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return cleaned
    repaired = compact_whitespace(repaired)
    if repaired and repaired != cleaned:
        return repaired
    return cleaned


def is_suspicious_keyword(value: str) -> bool:
    if not value:
        return True
    if "�" in value:
        return True
    if has_cjk(value):
        return False
    latin1_count = sum(1 for char in value if char in COMMON_MOJIBAKE_CHARS)
    ascii_word_count = sum(1 for char in value if char.isascii() and char.isalnum())
    if len(value) <= 2 and latin1_count == len(value):
        return True
    return latin1_count >= 2 and ascii_word_count <= 2


def normalize_keyword(value: str) -> str:
    cleaned = repair_mojibake(value)
    return "" if is_suspicious_keyword(cleaned) else cleaned


@lru_cache(maxsize=4096)
def char_width(char: str) -> int:
    if unicodedata.combining(char):
        return 0
    return 2 if unicodedata.east_asian_width(char) in {"W", "F"} else 1


@lru_cache(maxsize=4096)
def display_width(value: str) -> int:
    return sum(char_width(char) for char in value)


def truncate_display(value: str, width: int, placeholder: str = "...") -> str:
    cleaned = compact_whitespace(value)
    if width <= 0:
        return ""
    if display_width(cleaned) <= width:
        return cleaned
    placeholder_width = display_width(placeholder)
    if placeholder_width >= width:
        result = ""
        current_width = 0
        for char in placeholder:
            char_len = char_width(char)
            if current_width + char_len > width:
                break
            result += char
            current_width += char_len
        return result

    result = ""
    current_width = 0
    for char in cleaned:
        char_len = char_width(char)
        if current_width + char_len + placeholder_width > width:
            break
        result += char
        current_width += char_len
    return result.rstrip() + placeholder


def wrap_display(value: str, width: int) -> list[str]:
    cleaned = compact_whitespace(value)
    if not cleaned:
        return [""]
    if width <= 1:
        return [cleaned]

    lines: list[str] = []
    current = ""
    current_width = 0
    for char in cleaned:
        char_len = char_width(char)
        if current and current_width + char_len > width:
            lines.append(current.rstrip())
            if char.isspace():
                current = ""
                current_width = 0
            else:
                current = char
                current_width = char_len
            continue
        if not current and char.isspace():
            continue
        current += char
        current_width += char_len
    if current:
        lines.append(current.rstrip())
    return lines or [""]


def centered_x(total_width: int, text: str, min_x: int = 0) -> int:
    return max(min_x, (total_width - display_width(text)) // 2)


def shorten(value: str, width: int = 96) -> str:
    return truncate_display(value, width)


def human_count(value: int | None) -> str:
    if value is None:
        return "-"
    if value >= 100_000_000:
        return f"{value / 100_000_000:.1f}亿"
    if value >= 10_000:
        return f"{value / 10_000:.1f}万"
    return str(value)


def format_timestamp(value: int | None) -> str:
    if not value:
        return "-"
    return dt.datetime.fromtimestamp(value).strftime("%Y-%m-%d %H:%M")


def normalize_duration(value: str | int | None) -> str:
    if value is None:
        return "-"
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.isdigit():
            return normalize_duration(int(stripped))
        if ":" in stripped:
            parts = stripped.split(":")
            if all(part.isdigit() for part in parts):
                numbers = [int(part) for part in parts]
                if len(numbers) == 2:
                    return f"{numbers[0]}:{numbers[1]:02d}"
                if len(numbers) == 3:
                    return f"{numbers[0]}:{numbers[1]:02d}:{numbers[2]:02d}"
        return stripped
    minutes, seconds = divmod(int(value), 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"
