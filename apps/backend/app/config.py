from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')
    app_secret: str = 'INSECURE_DEVELOPMENT_ONLY'
    database_url: str = 'sqlite:///./galant-dev.db'
    document_dir: Path = Path('/tmp/galant-documents')
    max_upload_mb: int = 25
    max_pdf_pages: int = 50
    ocr_lang: str = 'spa+eng'
    cookie_secure: bool = False
    session_hours: int = 8
    worker_poll_seconds: float = 2.0

@lru_cache
def get_settings() -> Settings:
    return Settings()
