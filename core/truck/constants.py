"""Truck-scene constants.
卡车场景常量。

Truck-specific model names, labels, action requirements, tracker tuning and
daily-summary settings are kept here so generic core components stay scene-
agnostic.
truck 场景相关的模型名、标签、动作要求、跟踪参数和每日总结配置统一放在这里，
使通用 core 组件保持场景无关。
"""

from __future__ import annotations

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
    {"action1", "action2", "action3", "action4", "action5", "action6"}
)
"""Required actions during a truck visit. 卡车到访期间要求识别到的动作。"""

OTHER_ACTION_LABEL: str = "other"
"""Classification label for the non-required other class. 非必需 other 分类标签。"""

OCR_INTERVAL: int = 10
"""Frames between OCR attempts for the same truck. 同一卡车 OCR 间隔帧数。"""

MAX_MISSING_FRAMES: int = 30
"""Max consecutive missing frames before departure. 离场前允许的最大丢失帧数。"""

MIN_PRESENCE_FRAMES: int = 16
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
    "action1": "动作1",
    "action2": "动作2",
    "action3": "动作3",
    "action4": "动作4",
    "action5": "动作5",
    "action6": "动作6",
    "ExteriorInspectionOfTruck": "车身外检",
    "InnerInspectionOfTruck": "车内检查",
    "TakePhotoOfGoods": "货物拍照",
    "TakePhotoOfSeal": "铅封拍照",
    "other": "其他",
    "unknown": "未知",
    "none": "无",
}
"""English-to-Chinese labels for truck-scene messages. truck 场景中英文标签映射。"""
