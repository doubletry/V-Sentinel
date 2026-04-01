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

MAX_MISSING_FRAMES: int = 15
"""Consecutive frames without detection before truck departure.
连续未检测到卡车的帧数上限，超过后认为离开。

**Tuning guide / 调参指南**:
  Increase this value when trucks may pause or be momentarily occluded while
  still present.  At 25 fps with ``FRAME_SAMPLE_INTERVAL=3``, effective
  processing rate is ~8 fps, so 15 processed frames ≈ ~1.8 s real-time gap
  tolerance.  Decrease to react faster to genuine departures.
  当卡车可能暂停或短暂被遮挡时增大此值。在 25fps 且
  ``FRAME_SAMPLE_INTERVAL=3`` 时，实际处理约 8fps，15 帧处理 ≈ 约 1.8 秒
  的实时间隙容忍度。减小此值可更快响应真正离开。"""

MIN_PRESENCE_FRAMES: int = 8
"""Minimum consecutive detections to confirm a truck (filter transients).
确认卡车所需的最少连续检测帧数（过滤路过车辆）。

**Tuning guide / 调参指南**:
  Vehicles may stay in frame for several seconds.  With
  ``FRAME_SAMPLE_INTERVAL=3`` at 25 fps (~8 effective fps), 8 processed
  frames ≈ ~1 s.  Increase to filter longer transients; decrease (min 1) to
  confirm faster.
  车辆可能在画面中停留数秒。在 ``FRAME_SAMPLE_INTERVAL=3`` 且 25fps
  （约 8 有效 fps）时，8 帧处理 ≈ 约 1 秒。增大以过滤更长的瞬态检测；
  减小（最小 1）以更快确认。"""

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

# ── Frame sampling / 帧采样 ──────────────────────────────────────────────────

FRAME_SAMPLE_INTERVAL: int = 3
"""Process every N-th frame from the RTSP stream; skip the rest.
从 RTSP 流中每 N 帧处理一帧，跳过其余帧。

**Tuning guide / 调参指南**:
  Set to 1 to process every frame (no skipping).  At 25 fps, an interval of
  3 yields ~8 effective processing fps, which is usually sufficient for
  truck monitoring while reducing GPU/CPU load by ~67%.
  设为 1 则处理每帧（不跳过）。在 25fps 时，间隔 3 得到约 8 有效处理 fps，
  通常足以用于卡车监控，同时减少约 67% 的 GPU/CPU 负载。"""

# ── RTSP reconnection / RTSP 重连 ────────────────────────────────────────────

RTSP_RECONNECT_DELAY: float = 3.0
"""Seconds to wait before attempting to reconnect a failed RTSP reader.
RTSP 读取失败后重连前的等待秒数。"""

RTSP_MAX_RECONNECT_ATTEMPTS: int = 0
"""Maximum number of consecutive reconnection attempts.  0 = unlimited.
连续重连尝试的最大次数。0 = 无限制。"""

# ── Daily summary / 每日总结 ──────────────────────────────────────────────────

DAILY_SUMMARY_HOUR: int = 23
"""Hour of day (0-23, local time) to generate the daily vehicle-visit summary.
每日车辆到访总结的生成时间（本地时间 0-23 时）。"""

DAILY_SUMMARY_MINUTE: int = 59
"""Minute of the hour to generate the daily summary.
每日总结的分钟数。"""

# ── English → Chinese label mapping / 英中标签对照表 ─────────────────────────

LABEL_EN_TO_ZH: dict[str, str] = {
    "truck": "卡车",
    "person": "行人",
    "action1": "动作1",
    "action2": "动作2",
    "action3": "动作3",
    "action4": "动作4",
    "action5": "动作5",
    "action6": "动作6",
    "other": "其他",
    "unknown": "未知",
}
"""Map English classification / detection labels to Chinese for daily summaries.
将英文分类/检测标签映射为中文，用于每日总结。

Add new entries here when new models or label sets are deployed.
部署新模型或标签集时在此添加新条目。"""
