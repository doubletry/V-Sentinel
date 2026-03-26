from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")

    # V-Engine service addresses
    detection_addr: str = "localhost:50051"
    classification_addr: str = "localhost:50052"
    action_addr: str = "localhost:50053"
    ocr_addr: str = "localhost:50054"
    upload_addr: str = "localhost:50050"

    # MediaMTX
    mediamtx_rtsp_addr: str = "rtsp://localhost:8554"
    mediamtx_webrtc_addr: str = "http://localhost:8889"

    # App
    app_name: str = "V-Sentinel"
    database_url: str = "sqlite+aiosqlite:///./v_sentinel.db"
    db_path: str = "./v_sentinel.db"

    # Thread pool sizes
    max_pull_workers: int = 20
    max_push_workers: int = 10
    max_cpu_workers: int = 16


settings = Settings()
