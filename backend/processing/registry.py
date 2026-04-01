from __future__ import annotations

from typing import Type

from backend.processing.base import BaseVideoProcessor
from backend.processing.example import ExampleProcessor
from backend.processing.truck import TruckMonitorProcessor


PROCESSOR_PLUGINS: dict[str, Type[BaseVideoProcessor]] = {
    "example": ExampleProcessor,
    "truck": TruckMonitorProcessor,
}


def resolve_processor_class(plugin_name: str) -> Type[BaseVideoProcessor]:
    """Resolve a processor plugin name to its backend adapter class.
    将处理器插件名称解析为对应的 backend 适配类。"""
    try:
        return PROCESSOR_PLUGINS[plugin_name]
    except KeyError as exc:
        available = ", ".join(sorted(PROCESSOR_PLUGINS))
        raise ValueError(
            f"Unknown processor plugin: {plugin_name}. Available: {available}"
        ) from exc