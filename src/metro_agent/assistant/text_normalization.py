from __future__ import annotations

import re

_FULL_WIDTH_DIGITS = str.maketrans("０１２３４５６７８９", "0123456789")
_CHINESE_DIGITS = {
    "零": 0,
    "〇": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}


def normalize_user_question(value: str) -> str:
    """Normalize harmless wording variants before deterministic intent routing."""

    normalized = value.translate(_FULL_WIDTH_DIGITS)
    normalized = re.sub(r"(?<=[号线站点路])到情况", "的情况", normalized)
    normalized = normalized.replace("线路到情况", "线路的情况")
    normalized = re.sub(
        r"([零〇一二两三四五六七八九十百]+)\s*号线",
        lambda match: f"{_chinese_integer(match.group(1))}号线",
        normalized,
    )
    return re.sub(r"(\d+)\s*号线", r"\1号线", normalized)


def extract_line_numbers(value: str) -> list[int]:
    normalized = normalize_user_question(value)
    return list(dict.fromkeys(int(item) for item in re.findall(r"(\d+)号线", normalized)))


def line_number(value: str) -> int | None:
    normalized = normalize_user_question(value).lower().replace(" ", "")
    patterns = (
        r"(\d+)号线",
        r"line[\s\-_]?([0-9]+)",
        r"^l[-_]?([0-9]+)$",
    )
    for pattern in patterns:
        match = re.search(pattern, normalized)
        if match:
            return int(match.group(1))
    return None


def entity_match_keys(value: str, entity_type: str) -> set[str]:
    """Build conservative aliases for matching a requested entity to observed labels."""

    normalized = normalize_user_question(value).lower()
    compact = re.sub(r"[\s，,。！？!?：:（）()\-_]", "", normalized)
    keys = {compact} if compact else set()
    if entity_type == "line":
        number = line_number(normalized)
        if number is not None:
            keys.update({str(number), f"{number}线", f"{number}号线", f"line{number}", f"l{number}"})
        stripped = re.sub(r"^[\u4e00-\u9fff]{0,8}地铁(?=\d+号线)", "", compact)
        stripped = re.sub(r"^(?:地铁|轨道交通|线路)", "", stripped)
        if stripped:
            keys.add(stripped)
    elif entity_type == "station":
        stripped = re.sub(r"(?:地铁站|车站|站点|站)$", "", compact)
        if stripped:
            keys.add(stripped)
    return {item for item in keys if item}


def _chinese_integer(value: str) -> int:
    if not any(unit in value for unit in ("十", "百")):
        digits = "".join(str(_CHINESE_DIGITS[item]) for item in value)
        return int(digits)

    total = 0
    current = 0
    for item in value:
        if item in _CHINESE_DIGITS:
            current = _CHINESE_DIGITS[item]
        elif item == "十":
            total += (current or 1) * 10
            current = 0
        elif item == "百":
            total += (current or 1) * 100
            current = 0
    return total + current
