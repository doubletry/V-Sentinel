# V-Sentinel

**AI Video Surveillance Analysis Platform**

V-Sentinel is a full-stack video surveillance AI analysis platform that integrates with the [V-Engine](https://github.com/doubletry/V-Engine) gRPC AI inference microservice. It provides a Vue 3 frontend for live video monitoring and a high-concurrency FastAPI backend for real-time multi-camera AI analysis.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                        V-Sentinel Platform                           │
│                                                                      │
│  ┌─────────────────┐         ┌──────────────────────────────────┐   │
│  │  Vue 3 Frontend │◄──WS────│         FastAPI Backend          │   │
│  │  (Element Plus) │◄──REST──│    (uvicorn, asyncio, grpc.aio)  │   │
│  └────────┬────────┘         └──────────────┬───────────────────┘   │
│           │                                 │                       │
│           │ WebRTC (WHEP)                   │ gRPC (async)          │
│           ▼                                 ▼                       │
│  ┌─────────────────┐         ┌──────────────────────────────────┐   │
│  │    MediaMTX     │         │          V-Engine                │   │
│  │  (RTSP→WebRTC)  │         │  Detection / Classification /   │   │
│  └─────────────────┘         │  Action / OCR / Upload           │   │
│                               └──────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────┘

Backend Async Processing Architecture:
┌─────────────────────────────────────────────────────────────────┐
│  Thread Pool: RTSP Frame Pulling (1 thread per camera)          │
│  ┌─────────────────────────────────────────────────┐            │
│  │ av.open(rtsp) → decode → jpeg.encode → Queue   │            │
│  └─────────────────────┬───────────────────────────┘            │
│                        │ frames via asyncio.Queue               │
│                        ▼                                        │
│  AsyncIO Event Loop (single thread, all coroutines)             │
│  ┌─────────────────────────────────────────────────┐            │
│  │ Camera-1: await process_frame()                 │            │
│  │   ├─ await vengine.detect()   (gRPC I/O)        │            │
│  │   ├─ await vengine.ocr()      (gRPC I/O)        │            │
│  │   ├─ asyncio.gather(detect, ocr) — concurrent  │            │
│  │   └─ ws_manager.broadcast()                     │            │
│  │ Camera-2: (interleaved)                         │            │
│  │ Camera-N: ...                                   │            │
│  └─────────────────────────────────────────────────┘            │
└─────────────────────────────────────────────────────────────────┘
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | Vue 3 + Element Plus + Vite |
| Backend | FastAPI (Python, fully async) |
| Video Streaming | MediaMTX (RTSP → WebRTC) |
| AI Inference | V-Engine gRPC microservices |
| gRPC Client | grpc.aio (async gRPC) |
| Real-time | WebSocket |
| Python Env | uv + pyproject.toml |
| Database | SQLite via aiosqlite |

---

## Prerequisites

- **Node.js** >= 18
- **Python** >= 3.11
- **uv** — [install](https://docs.astral.sh/uv/getting-started/installation/)
- **MediaMTX** — [download](https://github.com/bluenviron/mediamtx/releases) or use Docker
- **V-Engine** — running gRPC microservices (see [V-Engine repo](https://github.com/doubletry/V-Engine))

---

## Quick Start

### 1. Clone and install dependencies

```bash
git clone https://github.com/doubletry/V-Sentinel.git
cd V-Sentinel

# Install Python dependencies
uv sync
```

### 2. Start the backend

```bash
uv run uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

API documentation: http://localhost:8000/docs

### 3. Start the frontend (dev mode)

```bash
cd frontend
npm install
npm run dev
```

The frontend will be available at http://localhost:5173

### 4. Build frontend for production

```bash
cd frontend
npm run build
```

FastAPI automatically serves the built frontend from `/` when `frontend/dist/` exists.

---

## Configuration

Create a `.env` file in the project root to override defaults:

```dotenv
# V-Engine service addresses
DETECTION_ADDR=localhost:50051
CLASSIFICATION_ADDR=localhost:50052
ACTION_ADDR=localhost:50053
OCR_ADDR=localhost:50054
UPLOAD_ADDR=localhost:50050

# MediaMTX
MEDIAMTX_RTSP_ADDR=rtsp://localhost:8554
MEDIAMTX_WEBRTC_ADDR=http://localhost:8889

# Database
DB_PATH=./v_sentinel.db
```

---

## Proto Generation

The repository includes pre-generated stub files in `backend/proto/`. To regenerate from source `.proto` files:

```bash
cd backend/proto
./generate.sh
```

---

## Creating a Custom Processor

Subclass `BaseVideoProcessor` in `backend/processing/`:

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

Register it in `ProcessorManager.start_processor()`.

---

## API Reference

### Sources

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/sources` | Create video source |
| `GET` | `/api/sources` | List all sources |
| `GET` | `/api/sources/{id}` | Get source with ROIs |
| `PUT` | `/api/sources/{id}` | Update source and ROIs |
| `DELETE` | `/api/sources/{id}` | Delete source |
| `GET` | `/api/sources/by-rtsp?rtsp_url=` | Get source by RTSP URL |

### Processor

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/processor/start` | Start AI analysis |
| `POST` | `/api/processor/stop` | Stop AI analysis |
| `GET` | `/api/processor/status` | Get all processor statuses |

### WebSocket

| Path | Description |
|------|-------------|
| `ws://localhost:8000/ws/messages` | Real-time analysis message stream |

---

## Docker Compose

```bash
docker-compose up mediamtx
```

---

## License

MIT License — see [LICENSE](LICENSE) for details.
