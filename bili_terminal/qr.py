"""Small QR Code generator for local login pages.

This module intentionally uses only the Python standard library so login QR
generation never needs a network service or an optional dependency.
"""

from __future__ import annotations

import base64
from functools import lru_cache


_ECC_LEVEL_L = 1
_FORMAT_MASK = 0x5412
_FORMAT_GENERATOR = 0x537
_VERSION_GENERATOR = 0x1F25

_RS_BLOCKS_L: dict[int, tuple[int, tuple[int, ...]]] = {
    1: (7, (19,)),
    2: (10, (34,)),
    3: (15, (55,)),
    4: (20, (80,)),
    5: (26, (108,)),
    6: (18, (68, 68)),
    7: (20, (78, 78)),
    8: (24, (97, 97)),
    9: (30, (116, 116)),
    10: (18, (68, 68, 69, 69)),
    11: (20, (81, 81, 81, 81)),
    12: (24, (92, 92, 93, 93)),
    13: (26, (107, 107, 107, 107)),
    14: (30, (115, 115, 115, 116)),
    15: (22, (87, 87, 87, 87, 87, 88)),
    16: (24, (98, 98, 98, 98, 98, 99)),
    17: (28, (107, 108, 108, 108, 108, 108)),
    18: (30, (120, 120, 120, 120, 120, 121)),
    19: (28, (113, 113, 113, 114, 114, 114, 114)),
    20: (28, (107, 107, 107, 108, 108, 108, 108, 108)),
}

_ALIGNMENT_POSITIONS: dict[int, tuple[int, ...]] = {
    1: (),
    2: (6, 18),
    3: (6, 22),
    4: (6, 26),
    5: (6, 30),
    6: (6, 34),
    7: (6, 22, 38),
    8: (6, 24, 42),
    9: (6, 26, 46),
    10: (6, 28, 50),
    11: (6, 30, 54),
    12: (6, 32, 58),
    13: (6, 34, 62),
    14: (6, 26, 46, 66),
    15: (6, 26, 48, 70),
    16: (6, 26, 50, 74),
    17: (6, 30, 54, 78),
    18: (6, 30, 56, 82),
    19: (6, 30, 58, 86),
    20: (6, 34, 62, 90),
}


def qr_matrix(text: str) -> list[list[bool]]:
    """Return a Model 2 QR matrix for the UTF-8 bytes in *text*."""

    payload = text.encode("utf-8")
    version = _choose_version(len(payload))
    codewords = _encode_payload(payload, version)
    matrix, reserved = _make_base_matrix(version)
    _place_data_bits(matrix, reserved, _codewords_to_bits(_add_error_correction(codewords, version)))

    candidates: list[tuple[int, list[list[bool]]]] = []
    for mask in range(8):
        candidate = [row[:] for row in matrix]
        _apply_mask(candidate, reserved, mask)
        _draw_format_bits(candidate, reserved, mask)
        candidates.append((_penalty(candidate), candidate))
    candidates.sort(key=lambda item: item[0])
    return candidates[0][1]


def qr_svg(text: str, *, border: int = 4) -> str:
    """Return a standalone SVG QR Code for *text*."""

    matrix = qr_matrix(text)
    if border < 0:
        raise ValueError("border must be non-negative")
    size = len(matrix) + border * 2
    rects = []
    for y, row in enumerate(matrix):
        for x, dark in enumerate(row):
            if dark:
                rects.append(f'<rect x="{x + border}" y="{y + border}" width="1" height="1"/>')
    modules = "".join(rects)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}" '
        f'shape-rendering="crispEdges">'
        f'<rect width="100%" height="100%" fill="#fff"/>'
        f'<g fill="#111">{modules}</g>'
        f"</svg>"
    )


def qr_svg_data_uri(text: str) -> str:
    """Return a data URI containing a local SVG QR Code for *text*."""

    encoded = base64.b64encode(qr_svg(text).encode("utf-8")).decode("ascii")
    return f"data:image/svg+xml;base64,{encoded}"


def _choose_version(payload_len: int) -> int:
    for version, (_, blocks) in _RS_BLOCKS_L.items():
        count_bits = 8 if version <= 9 else 16
        capacity_bits = sum(blocks) * 8
        if 4 + count_bits + payload_len * 8 <= capacity_bits:
            return version
    raise ValueError("text is too long for the local QR generator")


def _encode_payload(payload: bytes, version: int) -> list[int]:
    _, blocks = _RS_BLOCKS_L[version]
    capacity_bits = sum(blocks) * 8
    bits: list[int] = []
    _append_bits(bits, 0b0100, 4)
    _append_bits(bits, len(payload), 8 if version <= 9 else 16)
    for byte in payload:
        _append_bits(bits, byte, 8)

    _append_bits(bits, 0, min(4, capacity_bits - len(bits)))
    while len(bits) % 8:
        bits.append(0)

    codewords = [int("".join(str(bit) for bit in bits[index : index + 8]), 2) for index in range(0, len(bits), 8)]
    pad = 0xEC
    while len(codewords) < sum(blocks):
        codewords.append(pad)
        pad = 0x11 if pad == 0xEC else 0xEC
    return codewords


def _append_bits(bits: list[int], value: int, length: int) -> None:
    if value >= (1 << length):
        raise ValueError("value does not fit in requested bit length")
    for shift in range(length - 1, -1, -1):
        bits.append((value >> shift) & 1)


def _add_error_correction(codewords: list[int], version: int) -> list[int]:
    ecc_len, block_lengths = _RS_BLOCKS_L[version]
    blocks = []
    offset = 0
    for length in block_lengths:
        block = codewords[offset : offset + length]
        blocks.append((block, _rs_remainder(block, ecc_len)))
        offset += length

    result: list[int] = []
    max_data_len = max(len(block) for block, _ in blocks)
    for index in range(max_data_len):
        for block, _ in blocks:
            if index < len(block):
                result.append(block[index])
    for index in range(ecc_len):
        for _, ecc in blocks:
            result.append(ecc[index])
    return result


def _codewords_to_bits(codewords: list[int]) -> list[int]:
    return [(codeword >> shift) & 1 for codeword in codewords for shift in range(7, -1, -1)]


@lru_cache(maxsize=None)
def _gf_tables() -> tuple[list[int], list[int]]:
    exp = [0] * 512
    log = [0] * 256
    value = 1
    for index in range(255):
        exp[index] = value
        log[value] = index
        value <<= 1
        if value & 0x100:
            value ^= 0x11D
    for index in range(255, 512):
        exp[index] = exp[index - 255]
    return exp, log


def _gf_mul(left: int, right: int) -> int:
    if left == 0 or right == 0:
        return 0
    exp, log = _gf_tables()
    return exp[log[left] + log[right]]


@lru_cache(maxsize=None)
def _rs_generator(degree: int) -> tuple[int, ...]:
    coefficients = [1]
    exp, _ = _gf_tables()
    for index in range(degree):
        root = exp[index]
        next_coefficients = [0] * (len(coefficients) + 1)
        for offset, coefficient in enumerate(coefficients):
            next_coefficients[offset] ^= coefficient
            next_coefficients[offset + 1] ^= _gf_mul(coefficient, root)
        coefficients = next_coefficients
    return tuple(coefficients)


def _rs_remainder(data: list[int], degree: int) -> list[int]:
    generator = _rs_generator(degree)
    result = [0] * degree
    for byte in data:
        factor = byte ^ result.pop(0)
        result.append(0)
        if factor:
            for index, coefficient in enumerate(generator[1:]):
                result[index] ^= _gf_mul(coefficient, factor)
    return result


def _make_base_matrix(version: int) -> tuple[list[list[bool]], list[list[bool]]]:
    size = _version_size(version)
    matrix = [[False] * size for _ in range(size)]
    reserved = [[False] * size for _ in range(size)]

    _draw_finder(matrix, reserved, 0, 0)
    _draw_finder(matrix, reserved, size - 7, 0)
    _draw_finder(matrix, reserved, 0, size - 7)
    _draw_timing(matrix, reserved)
    _draw_alignment(matrix, reserved, version)
    _draw_dark_module(matrix, reserved)
    _reserve_format_areas(matrix, reserved)
    if version >= 7:
        _draw_version_bits(matrix, reserved, version)
    return matrix, reserved


def _version_size(version: int) -> int:
    return 21 + (version - 1) * 4


def _set_module(matrix: list[list[bool]], reserved: list[list[bool]], x: int, y: int, dark: bool) -> None:
    size = len(matrix)
    if 0 <= x < size and 0 <= y < size:
        matrix[y][x] = dark
        reserved[y][x] = True


def _draw_finder(matrix: list[list[bool]], reserved: list[list[bool]], left: int, top: int) -> None:
    for dy in range(-1, 8):
        for dx in range(-1, 8):
            x = left + dx
            y = top + dy
            dark = (
                0 <= dx <= 6
                and 0 <= dy <= 6
                and (dx in (0, 6) or dy in (0, 6) or (2 <= dx <= 4 and 2 <= dy <= 4))
            )
            _set_module(matrix, reserved, x, y, dark)


def _draw_timing(matrix: list[list[bool]], reserved: list[list[bool]]) -> None:
    size = len(matrix)
    for index in range(8, size - 8):
        dark = index % 2 == 0
        _set_module(matrix, reserved, index, 6, dark)
        _set_module(matrix, reserved, 6, index, dark)


def _draw_alignment(matrix: list[list[bool]], reserved: list[list[bool]], version: int) -> None:
    for center_y in _ALIGNMENT_POSITIONS[version]:
        for center_x in _ALIGNMENT_POSITIONS[version]:
            if reserved[center_y][center_x]:
                continue
            for dy in range(-2, 3):
                for dx in range(-2, 3):
                    distance = max(abs(dx), abs(dy))
                    _set_module(matrix, reserved, center_x + dx, center_y + dy, distance in (0, 2))


def _draw_dark_module(matrix: list[list[bool]], reserved: list[list[bool]]) -> None:
    _set_module(matrix, reserved, 8, len(matrix) - 8, True)


def _reserve_format_areas(matrix: list[list[bool]], reserved: list[list[bool]]) -> None:
    size = len(matrix)
    for index in range(15):
        if index < 6:
            _set_module(matrix, reserved, 8, index, False)
        elif index < 8:
            _set_module(matrix, reserved, 8, index + 1, False)
        else:
            _set_module(matrix, reserved, 8, size - 15 + index, False)

        if index < 8:
            _set_module(matrix, reserved, size - 1 - index, 8, False)
        elif index < 9:
            _set_module(matrix, reserved, 15 - index, 8, False)
        else:
            _set_module(matrix, reserved, 14 - index, 8, False)


def _draw_version_bits(matrix: list[list[bool]], reserved: list[list[bool]], version: int) -> None:
    size = len(matrix)
    bits = _version_bits(version)
    for index in range(18):
        bit = ((bits >> index) & 1) == 1
        x = size - 11 + index % 3
        y = index // 3
        _set_module(matrix, reserved, x, y, bit)
        _set_module(matrix, reserved, y, x, bit)


def _place_data_bits(matrix: list[list[bool]], reserved: list[list[bool]], bits: list[int]) -> None:
    size = len(matrix)
    bit_index = 0
    upward = True
    x = size - 1
    while x > 0:
        if x == 6:
            x -= 1
        rows = range(size - 1, -1, -1) if upward else range(size)
        for y in rows:
            for dx in (0, 1):
                module_x = x - dx
                if not reserved[y][module_x]:
                    matrix[y][module_x] = bit_index < len(bits) and bits[bit_index] == 1
                    bit_index += 1
        upward = not upward
        x -= 2


def _apply_mask(matrix: list[list[bool]], reserved: list[list[bool]], mask: int) -> None:
    for y, row in enumerate(matrix):
        for x in range(len(row)):
            if not reserved[y][x] and _mask_bit(mask, x, y):
                row[x] = not row[x]


def _mask_bit(mask: int, x: int, y: int) -> bool:
    if mask == 0:
        return (x + y) % 2 == 0
    if mask == 1:
        return y % 2 == 0
    if mask == 2:
        return x % 3 == 0
    if mask == 3:
        return (x + y) % 3 == 0
    if mask == 4:
        return (y // 2 + x // 3) % 2 == 0
    if mask == 5:
        return (x * y) % 2 + (x * y) % 3 == 0
    if mask == 6:
        return ((x * y) % 2 + (x * y) % 3) % 2 == 0
    if mask == 7:
        return ((x + y) % 2 + (x * y) % 3) % 2 == 0
    raise ValueError("mask must be between 0 and 7")


def _draw_format_bits(matrix: list[list[bool]], reserved: list[list[bool]], mask: int) -> None:
    size = len(matrix)
    bits = _format_bits(mask)
    for index in range(15):
        bit = ((bits >> index) & 1) == 1
        if index < 6:
            _set_module(matrix, reserved, 8, index, bit)
        elif index < 8:
            _set_module(matrix, reserved, 8, index + 1, bit)
        else:
            _set_module(matrix, reserved, 8, size - 15 + index, bit)

        if index < 8:
            _set_module(matrix, reserved, size - 1 - index, 8, bit)
        elif index < 9:
            _set_module(matrix, reserved, 15 - index, 8, bit)
        else:
            _set_module(matrix, reserved, 14 - index, 8, bit)
    matrix[size - 8][8] = True


def _format_bits(mask: int) -> int:
    data = (_ECC_LEVEL_L << 3) | mask
    bits = data << 10
    for index in range(14, 9, -1):
        if (bits >> index) & 1:
            bits ^= _FORMAT_GENERATOR << (index - 10)
    return ((data << 10) | bits) ^ _FORMAT_MASK


def _version_bits(version: int) -> int:
    bits = version << 12
    for index in range(17, 11, -1):
        if (bits >> index) & 1:
            bits ^= _VERSION_GENERATOR << (index - 12)
    return (version << 12) | bits


def _penalty(matrix: list[list[bool]]) -> int:
    score = _run_penalty(matrix)
    score += _block_penalty(matrix)
    score += _finder_penalty(matrix)
    score += _balance_penalty(matrix)
    return score


def _run_penalty(matrix: list[list[bool]]) -> int:
    score = 0
    rows = matrix
    columns = [[matrix[y][x] for y in range(len(matrix))] for x in range(len(matrix))]
    for line in rows + columns:
        run_color = line[0]
        run_len = 1
        for color in line[1:]:
            if color == run_color:
                run_len += 1
            else:
                if run_len >= 5:
                    score += 3 + run_len - 5
                run_color = color
                run_len = 1
        if run_len >= 5:
            score += 3 + run_len - 5
    return score


def _block_penalty(matrix: list[list[bool]]) -> int:
    score = 0
    size = len(matrix)
    for y in range(size - 1):
        for x in range(size - 1):
            color = matrix[y][x]
            if matrix[y][x + 1] == color and matrix[y + 1][x] == color and matrix[y + 1][x + 1] == color:
                score += 3
    return score


def _finder_penalty(matrix: list[list[bool]]) -> int:
    patterns = (
        (True, False, True, True, True, False, True, False, False, False, False),
        (False, False, False, False, True, False, True, True, True, False, True),
    )
    score = 0
    lines = list(matrix)
    lines += [[matrix[y][x] for y in range(len(matrix))] for x in range(len(matrix))]
    for line in lines:
        for index in range(len(line) - 10):
            if tuple(line[index : index + 11]) in patterns:
                score += 40
    return score


def _balance_penalty(matrix: list[list[bool]]) -> int:
    size = len(matrix)
    dark = sum(1 for row in matrix for module in row if module)
    percentage = dark * 100 // (size * size)
    return abs(percentage - 50) // 5 * 10
