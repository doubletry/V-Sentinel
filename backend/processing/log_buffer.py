from __future__ import annotations

from collections import deque
from math import ceil
from threading import Lock
from typing import Any


class ProcessingLogBuffer:
    """In-memory ring buffer for processing runtime logs with pagination.
    带分页功能的内存环形缓冲区，用于处理运行时日志。"""

    def __init__(self, max_entries: int = 2000) -> None:
        self._items: deque[dict[str, str]] = deque(maxlen=max_entries)
        self._lock = Lock()

    def append(self, *, timestamp: str, level: str, module: str, message: str) -> None:
        """Append a log entry to the ring buffer.
        向环形缓冲区追加一条日志。"""
        item = {
            "timestamp": timestamp,
            "level": level,
            "module": module,
            "message": message,
        }
        with self._lock:
            self._items.append(item)

    def list(self, page: int = 1, page_size: int = 20) -> dict[str, Any]:
        """Return a paginated slice of log entries (newest first).
        返回分页的日志条目切片（最新在前）。"""
        safe_page = max(page, 1)
        safe_size = max(page_size, 1)

        with self._lock:
            all_items = list(reversed(self._items))

        total = len(all_items)
        total_pages = ceil(total / safe_size) if total else 0
        start = (safe_page - 1) * safe_size
        end = start + safe_size
        items = all_items[start:end]

        return {
            "items": items,
            "page": safe_page,
            "page_size": safe_size,
            "total": total,
            "total_pages": total_pages,
        }


processing_log_buffer = ProcessingLogBuffer()
