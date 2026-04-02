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
_FALLBACK_PLATE_RE = re.compile(
    r"^(?=[A-Z0-9]{5,6}$)(?=.*[A-Z])[A-Z0-9]{5,6}$"
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
