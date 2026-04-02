from __future__ import annotations

from importlib import import_module
from typing import Any, Type

from backend.processing.base import BaseVideoProcessor
from backend.processing.example import ExampleProcessor
from backend.processing.truck import TruckMonitorProcessor
from backend.models.schemas import ProcessorPluginInfo


PROCESSOR_PLUGINS: dict[str, Type[BaseVideoProcessor]] = {
    "example": ExampleProcessor,
    "truck": TruckMonitorProcessor,
}


def _load_plugin_metadata(plugin_name: str) -> dict[str, Any]:
    """Load processor plugin metadata from the plugin package.
    从插件目录加载处理器插件元数据。"""
    metadata_module = import_module(f"backend.processing.{plugin_name}.metadata")
    return getattr(metadata_module, "PLUGIN_METADATA")


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


def list_processor_plugins() -> list[ProcessorPluginInfo]:
    """Return available processor plugins with display metadata.
    返回可用处理器插件及其展示元数据。"""
    result: list[ProcessorPluginInfo] = []
    for plugin_name in sorted(PROCESSOR_PLUGINS):
        meta = _load_plugin_metadata(plugin_name)
        result.append(
            ProcessorPluginInfo(
                value=plugin_name,
                label_zh=str(meta.get("label_zh", plugin_name)),
                label_en=str(meta.get("label_en", plugin_name)),
            )
        )
    return result
