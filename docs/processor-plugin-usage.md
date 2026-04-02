# 处理器模板与场景插件使用说明

本文档说明当前仓库中“通用模板 + 场景插件 + backend 适配层”的完整结构，以及如何启用 truck 场景或新增你自己的场景。

## 目录结构

```text
core/
  base_processor.py        # 通用视频处理模板（含 _do_detect/_do_ocr/_do_classify）
  analysis_agent.py        # 通用分析 agent 模板
  truck_processor.py       # truck 场景核心逻辑（与 backend 解耦）
  example_processor.py     # 最小示例场景

backend/processing/
  base.py                  # backend 通用适配层（WS/agent 生命周期）
  agent.py                 # backend agent 适配层（持久化/每日总结）
  truck.py                 # truck 场景 backend 适配层
  example.py               # example 场景 backend 适配层
  registry.py              # 插件注册表
  manager.py               # 根据 processor_plugin 选择插件并启动
```

## 当前可用插件

- `truck`: 车辆到访/车牌/OCR/动作检查场景
- `example`: 最小通用示例场景

## 如何启用 truck 场景

默认配置已经切到 `truck`，对应键为：

```json
{
  "processor_plugin": "truck"
}
```

这个键存放在应用设置里。当前可以通过以下任一方式修改：

1. 直接更新数据库 `app_settings` 表中的 `processor_plugin`
2. 通过后端设置接口 `PUT /api/settings` 提交：

```json
{
  "processor_plugin": "truck"
}
```

处理器启动时，[backend/processing/manager.py](backend/processing/manager.py) 会读取该值，并通过 [backend/processing/registry.py](backend/processing/registry.py) 解析到具体的 backend 适配类。

## truck 场景的分层

- [core/truck_processor.py](core/truck_processor.py)
  只保留场景逻辑：检测结果拆分、tracker 决策、visit 记录拼装

- [backend/processing/truck.py](backend/processing/truck.py)
  只负责 backend 适配：
  - WebSocket 广播
  - agent 提交
  - backend 生命周期接入

也就是说，truck 场景现在已经真正成为一个“core 场景插件 + backend 适配层”的闭环。

## BaseVideoProcessor 可复用能力

[core/base_processor.py](core/base_processor.py) 现在内置以下通用助手：

- `_do_detect(...)`
- `_do_ocr(...)`
- `_do_classify(...)`
- `_bbox_to_roi_points(...)`
- `_encode_thumbnail(...)`

推荐新场景处理器优先复用这几个方法，而不是直接调用 `self.vengine.detect/classify/ocr`。

### `_do_detect(...)`

适用场景：
- 单帧检测
- 批量检测
- 需要对检测结果做统一映射/过滤

典型写法：

```python
detect_result = await self._do_detect(
    shape=shape,
    model_name="your_model",
    conf=0.5,
    model_roi=primary_roi,
    image_key=image_key,
)
detections = detect_result["detections"]
```

如果需要在检测后立刻转换结构：

```python
def _map_detection(item: dict) -> dict | None:
    if item.get("confidence", 0.0) < 0.6:
        return None
    item["label"] = str(item.get("label", "")).lower()
    return item

detect_result = await self._do_detect(
    shape=shape,
    model_name="your_model",
    image_bytes=encoded,
    on_item=_map_detection,
)
```

### `_do_ocr(...)` 与 `_do_classify(...)`

这两个方法也支持 `on_item` 回调，适合把原始 RPC 结果直接映射到场景内部结构，避免每个处理器重复写样板代码。

## 如何新增一个自己的场景插件

### 第 1 步：在 core 中写场景处理器

新建 `core/my_scene_processor.py`：

```python
from core.base_processor import AnalysisResult, BaseVideoProcessor


class MySceneProcessor(BaseVideoProcessor):
    async def process_frame(self, frame, encoded, shape, roi_pixel_points):
        detect_result = await self._do_detect(
            shape=shape,
            model_name="my_model",
            image_bytes=encoded,
        )
        return AnalysisResult(detections=detect_result["detections"])
```

### 第 2 步：在 backend 中写适配层

新建 `backend/processing/my_scene.py`，模式与 [backend/processing/truck.py](backend/processing/truck.py) 一致：

```python
from backend.processing.base import BaseVideoProcessor
from core.my_scene_processor import MySceneProcessor as _CoreMySceneProcessor


class MySceneProcessor(BaseVideoProcessor, _CoreMySceneProcessor):
    pass
```

### 第 3 步：注册插件

在 [backend/processing/registry.py](backend/processing/registry.py) 中加入：

```python
PROCESSOR_PLUGINS["my_scene"] = MySceneProcessor
```

### 第 4 步：切换插件

把设置项改成：

```json
{
  "processor_plugin": "my_scene"
}
```

## agent 的模板化边界

- 通用聚合生命周期在 [core/analysis_agent.py](core/analysis_agent.py)
- 与业务强相关的内容在 [backend/processing/agent.py](backend/processing/agent.py)

truck 场景当前耦合在 backend agent 的部分主要是：
- 车辆到访记录持久化
- 每日中文总结

如果后续新增非 truck 场景，可以保留 `BaseAnalysisAgent` 不动，只新增一个场景专用 backend agent 子类即可。

## 建议的使用原则

- 场景无关的推理、聚合、缩略图、ROI 转换，一律下沉到 `core`
- backend 只保留框架接线、持久化、消息模型适配
- 每个场景只保留真正的业务状态机与业务语义
