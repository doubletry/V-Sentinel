"""Truck-scene constants.
卡车场景常量。

Truck-specific model names, labels, action requirements, tracker tuning and
daily-summary settings are kept here so generic core components stay scene-
agnostic.
truck 场景相关的模型名、标签、动作要求、跟踪参数和每日总结配置统一放在这里，
使通用 core 组件保持场景无关。
"""

from __future__ import annotations

from collections.abc import Iterable

DETECTION_MODEL: str = "huotai"
"""Default truck-scene detection model name. 默认 truck 场景检测模型名称。"""

CLASSIFICATION_MODEL: str = "huotai"
"""Default truck-scene classification model name. 默认 truck 场景分类模型名称。"""

OCR_MODEL: str = "paddleocr"
"""Default truck-scene OCR model name. 默认 truck 场景 OCR 模型名称。"""

TRUCK_LABELS: frozenset[str] = frozenset({"truck"})
"""Detection labels considered as truck. 被视为 truck 的检测标签。"""

PERSON_LABEL: str = "person"
"""Detection label for people. 行人的检测标签。"""

REQUIRED_ACTIONS: frozenset[str] = frozenset(
    {
        "HandOverKeys",
        "PlaceWheelChock",
        "InnerInspectionOfTruck",
        "ExteriorInspectionOfTruck",
        "TakePhotosOfGoods",
        "TakePhotosOfSeal",
    }
)
"""Required actions during a truck visit. 卡车到访期间要求识别到的动作。"""

OTHER_ACTION_LABEL: str = "Other"
"""Classification label for the non-required other class. 非必需 other 分类标签。"""

OCR_INTERVAL: int = 10
"""Frames between OCR attempts for the same truck. 同一卡车 OCR 间隔帧数。"""

MAX_MISSING_FRAMES: int = 500
"""Max consecutive missing frames before departure. 离场前允许的最大丢失帧数。"""

MIN_PRESENCE_FRAMES: int = 500
"""Frames needed to confirm a non-transient truck. 确认非路过卡车所需帧数。"""

STABILITY_WINDOW: int = 7
"""Majority-vote window for stable action classification. 稳定动作分类投票窗口。"""

STABILITY_MIN_COUNT: int = 3
"""Minimum count required for a stable action. 稳定动作所需最少出现次数。"""

DAILY_SUMMARY_HOUR: int = 23
"""Local hour to generate the truck daily summary. 生成 truck 每日总结的本地小时。"""

DAILY_SUMMARY_MINUTE: int = 59
"""Local minute to generate the truck daily summary. 生成 truck 每日总结的本地分钟。"""

LABEL_EN_TO_ZH: dict[str, str] = {
    "truck": "卡车",
    "person": "行人",
    "HandOverKeys": "上交钥匙",
    "PlaceWheelChock": "放三角木",
    "InnerInspectionOfTruck": "车内检查",
    "ExteriorInspectionOfTruck": "车外检查",
    "TakePhotosOfGoods": "货物拍照",
    "TakePhotosOfSeal": "封条拍照",
    "Other": "其他",
    "unknown": "未知",
}
"""English-to-Chinese labels for truck-scene messages. truck 场景中英文标签映射。"""

ACTION_LABEL_ALIASES: dict[str, str] = {
    "action1": "HandOverKeys",
    "action2": "PlaceWheelChock",
    "action3": "InnerInspectionOfTruck",
    "action4": "ExteriorInspectionOfTruck",
    "action5": "TakePhotosOfGoods",
    "action6": "TakePhotosOfSeal",
    "other": "Other",
    "takephotoofgoods": "TakePhotosOfGoods",
    "takephotosofseal": "TakePhotosOfSeal",
}
"""Canonical aliases for truck-scene classification labels. truck 场景分类标签规范化映射。"""


def translate_label(label: str) -> str:
    """Translate one truck-scene label to Chinese when known.
    将单个 truck 场景标签翻译为中文（如已知）。"""
    normalized = normalize_action_label(label)
    return LABEL_EN_TO_ZH.get(normalized, normalized)


def translate_labels(labels: Iterable[str] | None) -> list[str]:
    """Translate a list of truck-scene labels to Chinese.
    将一组 truck 场景标签翻译为中文。"""
    return [translate_label(str(label)) for label in labels or []]


def normalize_action_label(label: str) -> str:
    """Normalize one truck-scene classification label to its canonical value.
    将单个 truck 场景分类标签归一化为规范值。"""
    text = str(label or "").strip()
    return ACTION_LABEL_ALIASES.get(text, ACTION_LABEL_ALIASES.get(text.lower(), text))
