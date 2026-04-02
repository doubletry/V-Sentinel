"""Generic shared constants for the V-Sentinel core.
V-Sentinel core 的通用共享常量。

Only scene-agnostic constants stay here. Scene-specific values belong in the
corresponding scene package such as ``core.truck.constants``.
这里只保留场景无关常量。场景相关常量应放到对应场景目录，例如
``core.truck.constants``。
"""

from __future__ import annotations

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

EMAIL_PORT: str = "50055"
"""Default gRPC email-service port. 默认 gRPC 邮件服务端口。"""
