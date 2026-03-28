from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Minimal env-only settings: ports + DB path.

    All service addresses (V-Engine, MediaMTX) are stored in the database
    and managed via the Settings page in the web UI.
    """

    model_config = SettingsConfigDict(env_file=".env")

    # Server ports (env-only)
    backend_port: int = 8000
    frontend_port: int = 3000

    # Database path (env-only)
    db_path: str = "./v_sentinel.db"

    # App
    app_name: str = "V-Sentinel"


# Default values for DB-backed settings (used when no DB record exists)
DEFAULT_APP_SETTINGS: dict[str, str] = {
    # UI
    "ui_language": "zh-CN",
    "site_title": "V-Sentinel",
    "site_description": "AI Video Surveillance Analysis Platform",
    "favicon_url": "/favicon.ico",
    "roi_tag_options": "[\"person\", \"vehicle\", \"intrusion\"]",
    # Shared V-Engine host
    "vengine_host": "localhost",
    # Per-service ports
    "detection_port": "50051",
    "classification_port": "50052",
    "action_port": "50053",
    "ocr_port": "50054",
    "upload_port": "50050",
    # MediaMTX
    "mediamtx_rtsp_addr": "rtsp://localhost:8554",
    "mediamtx_webrtc_addr": "http://localhost:8889",
    # Thread pool sizes
    "max_pull_workers": "20",
    "max_push_workers": "10",
    "max_cpu_workers": "16",
}


settings = Settings()
