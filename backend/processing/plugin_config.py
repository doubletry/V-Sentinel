from __future__ import annotations

from typing import Any

from backend.db import database as db
from backend.processing.registry import get_plugin_metadata


def _runtime_config_key(plugin_name: str) -> str:
    return f"plugin_runtime_config:{plugin_name}"


def get_runtime_config_from_settings(
    app_settings: dict[str, str],
    plugin_name: str,
) -> dict[str, Any]:
    """Read a plugin runtime config JSON blob from app settings.
    从应用设置中读取插件运行时配置 JSON。"""
    import json

    raw = app_settings.get(_runtime_config_key(plugin_name), "")
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _constant_defaults(schema: dict[str, Any]) -> dict[str, Any]:
    return {
        str(item.get("key")): item.get("default")
        for item in schema.get("constants", [])
        if item.get("key")
    }


def _default_action_labels(schema: dict[str, Any]) -> list[dict[str, Any]]:
    action_schema = schema.get("action_labels") or {}
    labels = action_schema.get("default_labels") or []
    return [dict(item) for item in labels if isinstance(item, dict)]


def _normalize_action_labels(labels: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in labels:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label", "")).strip()
        if not label or label in seen:
            continue
        seen.add(label)
        display = str(item.get("display", "")).strip()
        result.append({
            "label": label,
            "display": display,
            "required": bool(item.get("required", False)),
            "source": str(item.get("source") or "custom"),
        })
    return result


def normalize_plugin_config(
    plugin_name: str,
    config: dict[str, Any] | None,
) -> dict[str, Any]:
    """Validate and normalize a plugin runtime config against metadata.
    根据插件元数据校验并规范化运行时配置。"""
    metadata = get_plugin_metadata(plugin_name)
    schema = dict(metadata.get("config_schema") or {})
    constant_defs = {
        str(item.get("key")): item
        for item in schema.get("constants", [])
        if item.get("key")
    }
    raw_config = config or {}
    raw_constants = raw_config.get("constants") or {}
    if not isinstance(raw_constants, dict):
        raise ValueError("constants must be an object")

    constants = _constant_defaults(schema)
    for key, value in raw_constants.items():
        if key not in constant_defs:
            raise ValueError(f"Unknown plugin config key: {key}")
        field = constant_defs[key]
        field_type = field.get("type")
        if field_type == "integer":
            try:
                normalized_value = int(value)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{key} must be an integer") from exc
            min_value = field.get("min")
            max_value = field.get("max")
            if min_value is not None and normalized_value < int(min_value):
                raise ValueError(f"{key} must be >= {min_value}")
            if max_value is not None and normalized_value > int(max_value):
                raise ValueError(f"{key} must be <= {max_value}")
            constants[key] = normalized_value
        else:
            constants[key] = str(value)

    default_labels = _normalize_action_labels(_default_action_labels(schema))
    raw_action_labels = raw_config.get("action_labels")
    if raw_action_labels is None:
        action_labels = default_labels
    elif not isinstance(raw_action_labels, list):
        raise ValueError("action_labels must be an array")
    else:
        action_labels = _normalize_action_labels(raw_action_labels)

    return {
        "constants": constants,
        "action_labels": action_labels,
    }


async def build_plugin_runtime_config_response(plugin_name: str) -> dict[str, Any]:
    """Return metadata, saved config, and merged label candidates for a plugin.
    返回插件元数据、已保存配置与合并后的标签候选。"""
    metadata = get_plugin_metadata(plugin_name)
    saved = await db.get_plugin_runtime_config(plugin_name)
    config = normalize_plugin_config(plugin_name, saved)
    schema = dict(metadata.get("config_schema") or {})
    default_labels = _normalize_action_labels(_default_action_labels(schema))
    observed = await db.list_plugin_label_candidates(plugin_name)

    candidates: dict[str, dict[str, Any]] = {}
    for item in default_labels:
        candidates[item["label"]] = {
            "label": item["label"],
            "display": item.get("display", ""),
            "required": bool(item.get("required", False)),
            "source": "default",
            "last_seen": "",
        }
    for item in observed:
        label = item["label"]
        existing = candidates.get(label, {})
        candidates[label] = {
            "label": label,
            "display": existing.get("display", ""),
            "required": bool(existing.get("required", False)),
            "source": "observed" if existing.get("source") != "default" else "default,observed",
            "last_seen": item.get("last_seen", ""),
        }
    for item in config["action_labels"]:
        label = item["label"]
        existing = candidates.get(label, {})
        candidates[label] = {
            "label": label,
            "display": item.get("display", existing.get("display", "")),
            "required": bool(item.get("required", existing.get("required", False))),
            "source": existing.get("source") or item.get("source") or "custom",
            "last_seen": existing.get("last_seen", ""),
        }

    return {
        "plugin": plugin_name,
        "config_schema": schema,
        "config": config,
        "label_candidates": sorted(candidates.values(), key=lambda item: item["label"]),
    }
