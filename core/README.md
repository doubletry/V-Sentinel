# V-Sentinel Core

**Minimal standalone package for independent Processor development.**

The `core` package provides a self-contained `BaseVideoProcessor` and a
simple runner so you can develop, test, and iterate on a video processor
without importing or running the full V-Sentinel backend.

Once your processor works in standalone mode, drop it into
`backend/processing/` and register it in `ProcessorManager` — no code
changes needed.

## Quick Start

```bash
# From the V-Sentinel root directory
pip install ./core            # or:  pip install ./core[grpc]

# Run the example
python -m core.example_processor --input rtsp://localhost:8554/cam1
```

## Writing a Custom Processor

```python
from core.base_processor import BaseVideoProcessor, AnalysisResult

class MyProcessor(BaseVideoProcessor):
    async def process_frame(self, frame, encoded, shape, roi_pixel_points):
        # Your AI logic here — call gRPC, run OpenCV, etc.
        annotated = self.draw_on_frame(frame, AnalysisResult())
        return AnalysisResult(annotated_frame=annotated)
```

## Running Standalone

```python
from core.runner import run_processor
from my_processor import MyProcessor

run_processor(
    MyProcessor,
    rtsp_input="rtsp://localhost:8554/cam1",
    mediamtx_rtsp_addr="rtsp://localhost:8554",
)
```

## Dependencies

| Package | Purpose |
|---------|---------|
| numpy | Frame arrays |
| opencv-python-headless | Drawing, color conversion |
| PyTurboJPEG | Fast JPEG encoding |
| av (PyAV) | RTSP reading/writing |
| loguru | Logging |
| grpcio (optional) | V-Engine gRPC calls |

## gRPC Proto Notes

- The source `.proto` files live in `backend/proto/`.
- Generated Python protobuf / gRPC files live in the canonical `core/proto/`
  package and should be regenerated with:

```bash
bash backend/proto/generate.sh
```

- ROI polygons sent to V-Engine now use integer pixel coordinates.
- Upload RPCs send `base.Image` / `base.Video` messages instead of raw
  `data + filename` fields, so the client wraps upload payloads before sending.
- `AsyncVEngineClient.detect()` / `classify()` also support batched
  `images=[{shape, image_key|image_bytes, roi?}, ...]` requests, so one cached
  frame key can be reused with multiple ROI-scoped `base.Image` entries in a
  single microservice call.

## Architecture

```
RTSP Input ──► Frame Reader Thread ──► asyncio.Queue ──► process_frame()
                                                              │
                                                    annotated_frame
                                                              │
                                                    Push Thread ──► MediaMTX RTSP Output
```

## License

MIT — same as the main V-Sentinel project.
