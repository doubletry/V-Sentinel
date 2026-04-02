# 将 core 处理器迁移到 backend/processing

本文档说明如何将在 `core/` 包中独立测试完成的处理器（如 `TruckMonitorProcessor`）迁移到 `backend/processing/` 中，使其能通过后端 API 管理生命周期、接入 WebSocket 广播和每日总结等后端功能。

---

## 架构概览

```
core/                           backend/processing/
├── base_processor.py           ├── base.py          (继承 core 基类，添加 WS/Agent)
├── truck_processor.py          ├── truck.py          ← 新建（继承 backend base）
├── truck_tracker.py            │                     (直接 import core.truck_tracker)
├── constants.py                └── manager.py        (注册新处理器)
└── runner.py (独立运行)
```

**核心原则**：`core/` 是**唯一的代码来源**（single source of truth），`backend/processing/` 只做后端特定扩展（WebSocket、Agent、DB 集成），不重复核心逻辑。

---

## 步骤 1：确认 core 处理器已完成测试

确保以下文件已通过测试：
- `core/truck_processor.py` — 主处理器
- `core/truck_tracker.py` — 跟踪器状态机
- `core/constants.py` — 相关常量

运行测试：
```bash
uv run pytest tests/test_truck.py tests/test_core.py -v
```

---

## 步骤 2：在 backend/processing/ 中创建后端处理器

创建 `backend/processing/truck.py`：

```python
"""Backend-integrated truck monitoring processor.
后端集成的卡车监控处理器。

Inherits all AI logic from ``core.truck_processor.TruckMonitorProcessor``
and adds backend integration (WebSocket broadcast, Agent aggregation).
继承 core.truck_processor.TruckMonitorProcessor 的所有 AI 逻辑，
添加后端集成（WebSocket 广播、Agent 聚合）。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from backend.models.schemas import ROI
from backend.processing.base import BaseVideoProcessor

# Import the core processor's process_frame logic via its tracker and constants.
# All AI logic stays in core — this file only provides the constructor glue.
from core.truck.processor import TruckMonitorProcessor as _CoreTruckProcessor

if TYPE_CHECKING:
    from backend.vengine.client import AsyncVEngineClient
    from backend.api.ws import WSManager
    from backend.processing.truck.agent import AnalysisAgent


class TruckMonitorProcessor(BaseVideoProcessor, _CoreTruckProcessor):
    """Backend-aware truck monitor that combines:
    - ``backend.processing.base.BaseVideoProcessor`` — WS, Agent, lifecycle
    - ``core.truck_processor.TruckMonitorProcessor`` — AI pipeline (process_frame)

    MRO ensures ``process_frame`` comes from the core processor while
    lifecycle/dispatch comes from the backend base.
    """

    def __init__(
        self,
        source_id: str,
        source_name: str,
        rtsp_url: str,
        rois: list[ROI],
        vengine_client: "AsyncVEngineClient",
        ws_manager: "WSManager",
        app_settings: dict[str, str],
        agent: "AnalysisAgent | None" = None,
    ) -> None:
        super().__init__(
            source_id=source_id,
            source_name=source_name,
            rtsp_url=rtsp_url,
            rois=rois,
            vengine_client=vengine_client,
            ws_manager=ws_manager,
            app_settings=app_settings,
            agent=agent,
        )
```

**关键**：利用 Python 的 MRO（方法解析顺序），`process_frame` 从 `_CoreTruckProcessor` 继承，而 `start/stop/_handle_result` 从 `BaseVideoProcessor` 继承。

---

## 步骤 3：在 manager.py 中注册新处理器

修改 `backend/processing/manager.py`，将 `ExampleProcessor` 替换为或新增 `TruckMonitorProcessor`：

```python
# 在文件顶部 import
from backend.processing.truck import TruckMonitorProcessor

# 在 start_processor 方法中，替换处理器创建逻辑：
processor = TruckMonitorProcessor(
    source_id=source.id,
    source_name=source.name,
    rtsp_url=source.rtsp_url,
    rois=source.rois,
    vengine_client=self._vengine,
    ws_manager=self._ws_manager,
    app_settings=self._app_settings,
    agent=self._agent,
)
```

如需支持多种处理器类型，可以在 `VideoSource` 模型中添加 `processor_type` 字段，根据类型选择处理器类。

---

## 步骤 4：验证迁移

1. **启动后端**：
   ```bash
   uv run uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
   ```

2. **通过 API 启动处理器**：
   ```bash
   curl -X POST http://localhost:8000/api/processor/start \
     -H "Content-Type: application/json" \
     -d '{"source_id": "<your-source-id>"}'
   ```

3. **检查 WebSocket 消息**：打开前端，确认收到检测消息和车辆离开通知。

4. **验证数据库记录**：使用 sqlite3 检查 `vehicle_visits` 表：
   ```bash
   sqlite3 v_sentinel.db "SELECT * FROM vehicle_visits ORDER BY created_at DESC LIMIT 5;"
   ```

---

## 注意事项

- **不要复制 core 代码到 backend**：所有 AI 逻辑保持在 core 中，backend 只做集成。
- **constants.py 是唯一配置源**：所有阈值、模型名称等在 `core/constants.py` 中修改。
- **TruckTracker 由 TruckMonitorProcessor 内部创建**：无需在 backend 层额外实例化。
- **测试**：迁移后运行 `uv run pytest tests/ -v` 确保原有测试不受影响。

---

## 参数调整指南

| 参数 | 位置 | 默认值 | 说明 |
|------|------|--------|------|
| `MIN_PRESENCE_FRAMES` | `core/constants.py` | 16 | 确认卡车所需最少连续检测帧数 |
| `MAX_MISSING_FRAMES` | `core/constants.py` | 30 | 卡车离开前允许的最大未检测帧数 |
| `FRAME_SAMPLE_INTERVAL` | `core/constants.py` | 3 | 每 N 帧处理一帧 |
| `OCR_INTERVAL` | `core/constants.py` | 10 | 同一卡车两次 OCR 之间的帧数 |
| `DAILY_SUMMARY_HOUR` | `core/constants.py` | 23 | 每日总结时间（小时） |
| `DAILY_SUMMARY_MINUTE` | `core/constants.py` | 59 | 每日总结时间（分钟） |
| `LABEL_EN_TO_ZH` | `core/constants.py` | (dict) | 英中标签对照表 |
