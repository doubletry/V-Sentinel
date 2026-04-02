"""Chinese truck-scene plate normalization helpers.
中文车牌归一化与过滤辅助函数。
"""

from __future__ import annotations

import re

_PROVINCE_PREFIX = (
    "京津沪渝冀豫云辽黑湘皖鲁新苏浙赣鄂桂甘晋蒙陕吉闽贵粤青藏川宁琼使领港澳"
)
_PLATE_RE = re.compile(
    rf"^(?:[{_PROVINCE_PREFIX}][A-Z])?[A-Z0-9]{{5,6}}$"
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
    return bool(_PLATE_RE.fullmatch(normalize_plate_text(text)))


def extract_valid_plate_text(text: str) -> str:
    """Return normalized plate text only when it is valid.
    仅当文本有效时返回归一化后的车牌文本。"""
    normalized = normalize_plate_text(text)
    if not normalized:
        return ""
    return normalized if _PLATE_RE.fullmatch(normalized) else ""
