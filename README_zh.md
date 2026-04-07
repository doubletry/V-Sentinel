[English](README.md)

# V-Sentinel

**AI 视频监控分析平台**

V-Sentinel 是一个全栈视频监控 AI 分析平台，与 [V-Engine](https://github.com/doubletry/V-Engine) gRPC AI 推理微服务深度集成。平台提供基于 Vue 3 的实时视频监控前端，以及高并发的 FastAPI 异步后端，支持多路摄像头实时 AI 分析。

---

## 系统架构

```
┌──────────────────────────────────────────────────────────────────────┐
│                        V-Sentinel 平台                                │
│                                                                      │
│  ┌─────────────────┐         ┌──────────────────────────────────┐   │
│  │  Vue 3 前端     │◄──WS────│         FastAPI 后端              │   │
│  │  (Element Plus) │◄──REST──│    (uvicorn, asyncio, grpc.aio)  │   │
│  └────────┬────────┘         └──────────────┬───────────────────┘   │
│           │                                 │                       │
│           │ WebRTC (WHEP)                   │ gRPC (异步)           │
│           ▼                                 ▼                       │
│  ┌─────────────────┐         ┌──────────────────────────────────┐   │
│  │ 外部 RTSP /     │         │          V-Engine                │   │
│  │ WebRTC 网关     │         │  检测 / 分类 / 行为分析 /        │   │
│  │ (如 MediaMTX)   │         │  OCR / 上传                       │   │
│  └─────────────────┘         │                                  │   │
│                               └──────────────────────────────────┘   │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  core/  — 独立处理器 SDK                                      │   │
│  │  可独立开发和测试处理器，完成后直接接入后端，无需修改代码。       │   │
│  └──────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────┘

后端异步处理架构：
┌─────────────────────────────────────────────────────────────────┐
│  线程池：RTSP 帧拉取（每个摄像头一个线程）                        │
│  ┌─────────────────────────────────────────────────┐            │
│  │ av.open(rtsp) → 解码 → TurboJPEG.encode → 队列 │            │
│  └─────────────────────┬───────────────────────────┘            │
│                        │ 帧数据通过 asyncio.Queue 传递           │
│                        ▼                                        │
│  AsyncIO 事件循环（单线程，所有协程）                              │
│  ┌─────────────────────────────────────────────────┐            │
│  │ 摄像头-1: await process_frame()                 │            │
│  │   ├─ await vengine.detect()   (gRPC I/O)        │            │
│  │   ├─ await vengine.ocr()      (gRPC I/O)        │            │
│  │   ├─ asyncio.gather(detect, ocr) — 并发执行     │            │
│  │   └─ ws_manager.broadcast()                     │            │
│  │ 摄像头-2: (交错执行)                             │            │
│  │ 摄像头-N: ...                                   │            │
│  └─────────────────────────────────────────────────┘            │
└─────────────────────────────────────────────────────────────────┘
```

---

## 技术栈

| 层级 | 技术 |
|---|---|
| 前端 | Vue 3 + Element Plus + Vite |
| 后端 | FastAPI（Python，全异步） |
| 视频流 | 外部 RTSP/WebRTC 网关（兼容 MediaMTX） |
| AI 推理 | V-Engine gRPC 微服务 |
| JPEG 编码 | TurboJPEG（通过 PyTurboJPEG） |
| RTSP 推流 | 每路摄像头维持持久化 av 容器 |
| gRPC 客户端 | grpc.aio（异步 gRPC） |
| 实时通信 | WebSocket |
| ROI 配置 | YAML 导入/导出（pyyaml） |
| Python 环境 | uv + pyproject.toml |
| 数据库 | SQLite（通过 aiosqlite） |
| 处理器 SDK | `core/` 独立包 |

---

## 前置要求

- **Node.js** >= 18
- **Python** >= 3.11
- **uv** — [安装指南](https://docs.astral.sh/uv/getting-started/installation/)
- **libturbojpeg** — PyTurboJPEG 依赖（Debian/Ubuntu 下：`apt install libturbojpeg0-dev`）
- **可选视频网关** — 仅当需要使用视频墙播放时，才需要准备兼容 MediaMTX 的 RTSP/WebRTC 网关
- **V-Engine** — 运行中的 gRPC 微服务（参见 [V-Engine 仓库](https://github.com/doubletry/V-Engine)）

---

## 快速开始

### 1. 克隆并安装依赖

```bash
git clone https://github.com/doubletry/V-Sentinel.git
cd V-Sentinel

# 安装 Python 依赖（包含 PyTurboJPEG、pyyaml 等所有依赖）
uv sync
```

### 2. 启动后端

```bash
# 默认端口 8000 — 可使用任意端口
uv run uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

API 文档地址：`http://localhost:<端口>/docs`

### 3. 启动前端（开发模式）

```bash
cd frontend
npm install

# Vite 开发代理默认指向后端 8000 端口。
# 如果后端运行在其他端口，可通过 VITE_BACKEND_PORT 覆盖：
#   VITE_BACKEND_PORT=9000 npm run dev
npm run dev
```

前端地址：http://localhost:5173

> **说明：** 前端所有 API 和 WebSocket 调用均使用相对 URL，因此可以配合任意后端端口
> 使用，无需硬编码地址。

### 4. 构建生产版本前端

```bash
cd frontend
npm run build
```

当 `frontend/dist/` 目录存在时，FastAPI 会自动从 `/` 提供构建后的前端静态文件。

---

## 配置

在项目根目录创建 `.env` 文件以覆盖默认配置：

```dotenv
# V-Engine 服务地址
DETECTION_ADDR=localhost:50051
CLASSIFICATION_ADDR=localhost:50052
ACTION_ADDR=localhost:50053
OCR_ADDR=localhost:50054
UPLOAD_ADDR=localhost:50050

# 可选外部视频网关（仅视频墙播放需要）
MEDIAMTX_RTSP_ADDR=rtsp://localhost:8554
MEDIAMTX_WEBRTC_ADDR=http://localhost:8889

# 数据库
DB_PATH=./v_sentinel.db
```

运行时消息缩略图会保存在数据库同级目录下的 `message_thumbnails/` 中。

### 前端代理端口

在开发模式下，Vite 开发服务器会将 `/api` 和 `/ws` 请求代理到后端。目标端口通过
`VITE_BACKEND_PORT` 环境变量读取（默认为 `8000`）：

```bash
VITE_BACKEND_PORT=9000 npm run dev
```

---

## Core 包 — 独立处理器 SDK

`core/` 目录是一个独立的 Python 包（`v-sentinel-core`），可让您在**不依赖完整后端**
的情况下开发和测试视频处理器。

### 安装

```bash
pip install ./core            # 最小安装
pip install ./core[grpc]      # 包含 V-Engine gRPC 支持
```

### 使用方法

```python
from core.base_processor import BaseVideoProcessor, AnalysisResult

class MyProcessor(BaseVideoProcessor):
    async def process_frame(self, frame, encoded, shape, roi_pixel_points):
        # 在此编写 AI 逻辑
        annotated = self.draw_on_frame(frame, AnalysisResult())
        return AnalysisResult(annotated_frame=annotated)
```

独立运行：

```python
from core.runner import run_processor
from my_processor import MyProcessor

run_processor(
    MyProcessor,
    rtsp_input="rtsp://localhost:8554/cam1",
    mediamtx_rtsp_addr="rtsp://localhost:8554",
)
```

开发完成后，在 `backend/processing/` 中增加一个薄适配层，
并在 `backend/processing/registry.py` 中注册，再通过 `processor_plugin`
设置切换即可。

详见 [`core/README.md`](core/README.md)。
插件化接入方式详见 [`docs/processor-plugin-usage.md`](docs/processor-plugin-usage.md)。

---

## Proto 生成

`.proto` 源文件与预生成的 Python 桩文件现统一位于 `core/proto/`。
如需重新生成：

```bash
bash core/proto/generate.sh
```

---

## 自定义处理器

在 `backend/processing/` 中继承 `BaseVideoProcessor`：

```python
from backend.processing.base import BaseVideoProcessor, AnalysisResult
from backend.models.schemas import AnalysisMessage
import asyncio
from datetime import datetime, timezone

class MyProcessor(BaseVideoProcessor):
    async def process_frame(self, frame, encoded, shape, roi_pixel_points):
        detections, ocr = await asyncio.gather(
            self.vengine.detect(encoded, shape, "yolov8n"),
            self.vengine.ocr(encoded, shape, "paddleocr"),
        )
        messages = []
        if detections:
            messages.append(AnalysisMessage(
                timestamp=datetime.now(timezone.utc).isoformat(),
                source_name=self.source_name,
                source_id=self.source_id,
                level="info",
                message=f"Detected: {', '.join(d['label'] for d in detections)}",
            ))
        result = AnalysisResult(detections=detections, ocr_texts=ocr, messages=messages)
        result.annotated_frame = await asyncio.to_thread(self.draw_on_frame, frame, result)
        return result
```

在 `backend/processing/registry.py` 中注册，然后设置：

```json
{
    "processor_plugin": "my_scene"
}
```

详见 [`docs/processor-plugin-usage.md`](docs/processor-plugin-usage.md)。

---

## API 参考

### 视频源

| 方法 | 路径 | 描述 |
|--------|------|-------------|
| `POST` | `/api/sources` | 创建视频源 |
| `GET` | `/api/sources` | 获取所有视频源 |
| `GET` | `/api/sources/{id}` | 获取视频源及 ROI 信息 |
| `PUT` | `/api/sources/{id}` | 更新视频源和 ROI |
| `DELETE` | `/api/sources/{id}` | 删除视频源 |
| `GET` | `/api/sources/by-rtsp?rtsp_url=` | 根据 RTSP URL 查询视频源 |

### ROI 导入 / 导出

| 方法 | 路径 | 描述 |
|--------|------|-------------|
| `GET` | `/api/sources/{id}/rois/export` | 导出 ROI 为 YAML |
| `POST` | `/api/sources/{id}/rois/import` | 从 YAML 导入 ROI（含标签验证） |

### 处理器

| 方法 | 路径 | 描述 |
|--------|------|-------------|
| `POST` | `/api/processor/start` | 启动 AI 分析 |
| `POST` | `/api/processor/stop` | 停止 AI 分析 |
| `GET` | `/api/processor/status` | 获取所有处理器状态 |

### WebSocket

| 路径 | 描述 |
|------|-------------|
| `/ws/messages` | 实时分析消息流 |

---

## Docker

仓库现已改为**单容器**部署方式。

```bash
./scripts/build_docker.sh
docker run -d \
  --name v-sentinel \
  -p 8000:8000 \
  -e DB_PATH=/app/data/v_sentinel.db \
  -v "$(pwd)/data:/app/data" \
  v-sentinel:latest
```

- 前端、REST API、WebSocket 和消息缩略图统一由 `8000` 端口提供
- 不再需要 `docker-compose`
- 镜像内不再打包 MediaMTX；如需视频墙播放，请在设置页配置外部 RTSP/WebRTC 网关

详见 [`docs/docker-deployment.md`](docs/docker-deployment.md)。

---

## 许可证

MIT 许可证 — 详见 [LICENSE](LICENSE)。
