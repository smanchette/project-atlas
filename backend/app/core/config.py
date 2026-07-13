from functools import lru_cache
from pathlib import Path

from pydantic import AnyHttpUrl
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Project Atlas"
    api_prefix: str = "/api"
    database_url: str = "sqlite:///./atlas.db"
    frontend_origin: AnyHttpUrl | str = "http://localhost:5173"
    seed_on_startup: bool = True
    ai_provider: str = "mock"
    ai_api_key: str | None = None
    media_root: Path = Path("media")
    media_public_url: str = "http://localhost:8000/media"
    media_max_upload_bytes: int = 10 * 1024 * 1024
    media_max_pixels: int = 40_000_000
    atlas_release_manifest_sha256: str | None = None

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


@lru_cache
def get_settings() -> Settings:
    return Settings()
