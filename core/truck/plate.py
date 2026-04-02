"""Chinese truck-scene plate normalization helpers.
中文车牌归一化与过滤辅助函数。
"""

from __future__ import annotations

import re

_PROVINCE_PREFIX = (
    "京津沪渝冀豫云辽黑湘皖鲁新苏浙赣鄂桂甘晋蒙陕吉闽贵粤青藏川宁琼使领港澳"
)
# Supported forms:
# 1. Province + region letter + 5/6 alnum chars, e.g. 粤B12345 / 粤B123456
# 2. Plain 5/6 alnum fallback captured by OCR without province prefix, e.g. BLX785.
#    This fallback still requires at least one letter to avoid accepting digit-only noise.
# 支持两种形式：
# 1. 省份简称 + 地区字母 + 5/6 位字母数字
# 2. OCR 丢失省份前缀时的 5/6 位纯字母数字形式，且至少包含一个字母，避免误接收纯数字噪声
_PREFIXED_PLATE_RE = re.compile(
    rf"^[{_PROVINCE_PREFIX}][A-Z][A-Z0-9]{{5,6}}$"
)
_FALLBACK_BODY_RE = r"[A-Z0-9]{5,6}"
_FALLBACK_PLATE_RE = re.compile(
    rf"^(?={_FALLBACK_BODY_RE}$)(?=.*[A-Z]).+$"
)
_SEPARATOR_RE = re.compile(r"[\s\-·.]+")


def normalize_plate_text(text: str) -> str:
    """Normalize OCR text before validation.
    在校验前归一化 OCR 文本。"""
    normalized = _SEPARATOR_RE.sub("", str(text or "").strip().upper())
    return normalized


def is_valid_plate_text(text: str) -> bool:
    """Return whether text matches supported Chinese plate forms.
    判断文本是否符合支持的中国车牌形式。"""
    normalized = normalize_plate_text(text)
    return bool(
        _PREFIXED_PLATE_RE.fullmatch(normalized)
        or _FALLBACK_PLATE_RE.fullmatch(normalized)
    )


def extract_valid_plate_text(text: str) -> str:
    """Return normalized plate text only when it is valid.
    仅当文本有效时返回归一化后的车牌文本。"""
    normalized = normalize_plate_text(text)
    if not normalized:
        return ""
    return normalized if is_valid_plate_text(normalized) else ""


def has_plate_prefix(text: str) -> bool:
    """Return whether text contains a province + region prefix.
    返回文本是否带有省份 + 地区前缀。"""
    normalized = normalize_plate_text(text)
    return bool(_PREFIXED_PLATE_RE.fullmatch(normalized))


def should_replace_plate(
    current_text: str,
    current_confidence: float,
    new_text: str,
    new_confidence: float,
) -> bool:
    """Return whether a new OCR result should replace the current plate.
    判断新的 OCR 结果是否应替换当前车牌。

    Preference order:
    1. Plate with province/region prefix (e.g. 粤B12345) wins over a shorter
       fallback without the prefix.
    2. If prefix completeness is tied, keep the longer normalized plate.
    3. If completeness is tied, keep the higher-confidence result.
    优先级：
    1. 带省份/地区前缀的结果优先于缺少前缀的回退结果。
    2. 若完整度相同，保留更长的归一化车牌。
    3. 若完整度相同，再保留更高置信度的结果。
    """
    current = normalize_plate_text(current_text)
    candidate = normalize_plate_text(new_text)
    if not candidate:
        return False
    if not current:
        return True

    current_rank = (
        1 if has_plate_prefix(current) else 0,
        len(current),
        float(current_confidence),
    )
    candidate_rank = (
        1 if has_plate_prefix(candidate) else 0,
        len(candidate),
        float(new_confidence),
    )
    return candidate_rank > current_rank
