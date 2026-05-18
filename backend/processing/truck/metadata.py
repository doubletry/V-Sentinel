"""Display and runtime-config metadata for the truck processor plugin.
truck 处理器插件的展示与运行时配置元数据。"""

from core.truck.constants import (
    LABEL_EN_TO_ZH,
    MAX_MISSING_FRAMES,
    MIN_PRESENCE_FRAMES,
    OCR_INTERVAL,
    REQUIRED_ACTIONS,
    STABILITY_MIN_COUNT,
    STABILITY_WINDOW,
)

DEFAULT_ACTION_LABELS = [
    {
        "label": label,
        "display": LABEL_EN_TO_ZH.get(label, label),
        "required": label in REQUIRED_ACTIONS,
        "source": "default",
    }
    for label in sorted({*REQUIRED_ACTIONS, "Other"})
]

PLUGIN_METADATA = {
    "label_zh": "truck（车辆到访场景）",
    "label_en": "truck (truck arrival scenario)",
    "config_schema": {
        "requires_restart_keys": [
            "OCR_INTERVAL",
            "MAX_MISSING_FRAMES",
            "MIN_PRESENCE_FRAMES",
            "STABILITY_WINDOW",
            "STABILITY_MIN_COUNT",
            "REQUIRED_ACTIONS",
            "LABEL_EN_TO_ZH",
        ],
        "constants": [
            {
                "key": "OCR_INTERVAL",
                "label_zh": "OCR 间隔帧数",
                "label_en": "OCR interval frames",
                "type": "integer",
                "min": 1,
                "default": OCR_INTERVAL,
                "requires_restart": True,
            },
            {
                "key": "MAX_MISSING_FRAMES",
                "label_zh": "离场判定丢失帧数",
                "label_en": "Departure missing-frame threshold",
                "type": "integer",
                "min": 1,
                "default": MAX_MISSING_FRAMES,
                "requires_restart": True,
            },
            {
                "key": "MIN_PRESENCE_FRAMES",
                "label_zh": "到达确认连续帧数",
                "label_en": "Arrival confirmation frames",
                "type": "integer",
                "min": 1,
                "default": MIN_PRESENCE_FRAMES,
                "requires_restart": True,
            },
            {
                "key": "STABILITY_WINDOW",
                "label_zh": "动作稳定窗口",
                "label_en": "Action stability window",
                "type": "integer",
                "min": 1,
                "default": STABILITY_WINDOW,
                "requires_restart": True,
            },
            {
                "key": "STABILITY_MIN_COUNT",
                "label_zh": "动作稳定最少次数",
                "label_en": "Action stability minimum count",
                "type": "integer",
                "min": 1,
                "default": STABILITY_MIN_COUNT,
                "requires_restart": True,
            },
        ],
        "action_labels": {
            "default_labels": DEFAULT_ACTION_LABELS,
            "required_actions_key": "REQUIRED_ACTIONS",
            "translation_key": "LABEL_EN_TO_ZH",
            "requires_restart": True,
        },
    },
}
