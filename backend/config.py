from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Minimal env-only settings: ports + DB path.
    最小化的仅环境变量配置：端口 + 数据库路径。

    All service addresses (V-Engine, MediaMTX) are stored in the database
    and managed via the Settings page in the web UI.
    所有服务地址（V-Engine、MediaMTX）存储在数据库中，通过 Web UI 设置页面管理。
    """

    model_config = SettingsConfigDict(env_file=".env")

    # Server ports (env-only) / 服务端口（仅环境变量）
    backend_port: int = 8000
    frontend_port: int = 3000

    # Database path (env-only) / 数据库路径（仅环境变量）
    db_path: str = "./v_sentinel.db"

    # App / 应用
    app_name: str = "V-Sentinel"


# Default values for DB-backed settings (used when no DB record exists)
# 数据库设置的默认值（当无数据库记录时使用）
DEFAULT_APP_SETTINGS: dict[str, str] = {
    # UI / 界面
    "ui_language": "zh-CN",
    "site_title": "V-Sentinel",
    "site_description": "AI Video Surveillance Analysis Platform",
    "favicon_url": "/favicon.ico",
    "roi_tag_options": "[\"person\", \"vehicle\", \"intrusion\"]",
    # Shared V-Engine host / 共享 V-Engine 主机
    "vengine_host": "localhost",
    # Per-service ports / 各服务端口
    "detection_port": "50051",
    "classification_port": "50052",
    "action_port": "50053",
    "ocr_port": "50054",
    "upload_port": "50050",
    # Per-service enable/disable switches (JSON booleans as strings) / 各服务启用/禁用开关（字符串形式的布尔值）
    "detection_enabled": "true",
    "classification_enabled": "true",
    "action_enabled": "true",
    "ocr_enabled": "true",
    "upload_enabled": "true",
    # Processor plugin / 处理器插件
    "processor_plugin": "truck",
    # MediaMTX
    "mediamtx_rtsp_addr": "rtsp://localhost:8554",
    "mediamtx_webrtc_addr": "http://localhost:8889",
    # Thread pool sizes / 线程池大小
    "max_pull_workers": "20",
    "max_push_workers": "10",
    "max_cpu_workers": "16",
}


settings = Settings()
