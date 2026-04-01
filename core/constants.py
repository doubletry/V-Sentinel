"""Centralized constants for the V-Sentinel pipeline.
V-Sentinel 流水线的集中常量定义。

All model names, label sets, intervals, and tuning parameters are defined
here as the **single source of truth**.  Both ``core`` and ``backend``
modules import from this file instead of hard-coding values.
所有模型名称、标签集、间隔和调优参数都在此定义为**唯一数据源**。
``core`` 和 ``backend`` 模块均从此文件导入，而非硬编码。
"""

from __future__ import annotations

# ── Model names / 模型名称 ───────────────────────────────────────────────────
# Change these when switching to a different model deployment.
# 切换到不同的模型部署时修改这些值。

DETECTION_MODEL: str = "huotai"
"""Default object-detection model name (V-Engine). 默认目标检测模型名称。"""

CLASSIFICATION_MODEL: str = "huotai"
"""Default image-classification model name (V-Engine). 默认图像分类模型名称。"""

OCR_MODEL: str = "paddleocr"
"""Default OCR model name (V-Engine). 默认 OCR 模型名称。"""

# ── Label sets / 标签集 ──────────────────────────────────────────────────────

TRUCK_LABELS: frozenset[str] = frozenset({"truck"})
"""Detection labels considered as "truck". 被视为 "truck" 的检测标签。"""

PERSON_LABEL: str = "person"
"""Detection label for people. 行人的检测标签。"""

# ── Required actions / 必需动作 ──────────────────────────────────────────────
# The 6 actions that must be observed during a truck visit.
# 卡车到访期间必须观测到的 6 类动作。

REQUIRED_ACTIONS: frozenset[str] = frozenset(
    {"action1", "action2", "action3", "action4", "action5", "action6"}
)

OTHER_ACTION_LABEL: str = "other"
"""Classification label for the 7th "other" class, excluded from required.
第 7 类 "other" 的分类标签，不计入必需动作。"""

# ── OCR & tracking intervals / OCR 和跟踪间隔 ───────────────────────────────

OCR_INTERVAL: int = 10
"""Frames between OCR attempts on the same truck. 同一卡车两次 OCR 之间的帧数。"""

MAX_MISSING_FRAMES: int = 5
"""Consecutive frames without detection before truck departure.
连续未检测到卡车的帧数上限，超过后认为离开。"""

MIN_PRESENCE_FRAMES: int = 3
"""Minimum consecutive detections to confirm a truck (filter transients).
确认卡车所需的最少连续检测帧数（过滤路过车辆）。"""

# ── Classification stability / 分类稳定性 ────────────────────────────────────

STABILITY_WINDOW: int = 7
"""Majority-vote sliding window size. 多数投票滑动窗口大小。"""

STABILITY_MIN_COUNT: int = 3
"""Minimum label occurrences in window for stable classification.
窗口内标签最少出现次数以认定为稳定分类。"""

# ── RTSP push defaults / RTSP 推流默认值 ─────────────────────────────────────

PUSH_FPS: int = 25
"""Default FPS for RTSP output. RTSP 输出的默认帧率。"""

PUSH_PRESET: str = "ultrafast"
"""x264 preset for RTSP push. RTSP 推流的 x264 预设。"""

RTSP_TRANSPORT: str = "tcp"
"""RTSP transport protocol for reading.  TCP avoids green-frame / mosaic
artifacts caused by UDP packet loss.
RTSP 读取传输协议。TCP 避免 UDP 丢包导致的绿帧/马赛克。"""

# ── Drawing / overlay defaults / 绘制/叠加默认值 ─────────────────────────────

DRAW_FONT_SCALE: float = 1.0
"""Font scale for text drawn on detection bounding boxes.
检测框上文本的字体缩放比例。"""

DRAW_FONT_THICKNESS: int = 2
"""Font thickness for text drawn on detection bounding boxes.
检测框上文本的字体粗细。"""

DRAW_DETECTION_COLOR: tuple[int, int, int] = (0, 255, 0)
"""BGR/RGB color for detection bounding boxes.  Green.
检测框的颜色。绿色。"""

DRAW_CLASSIFICATION_COLOR: tuple[int, int, int] = (255, 255, 0)
"""BGR/RGB color for classification labels on person boxes.  Yellow.
人物框分类标签的颜色。黄色。"""
