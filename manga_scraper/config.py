from functools import lru_cache
from typing import Literal

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    app_env: Literal["development", "staging", "production"] = "development"
    debug: bool = False
    secret_key: str = "change-me-in-production"

    # Database
    database_url: str = "postgresql+asyncpg://manga:manga@localhost:5432/manga_scraper"
    database_url_sync: str = "postgresql://manga:manga@localhost:5432/manga_scraper"

    # Redis
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"

    # S3/MinIO
    s3_endpoint_url: str | None = "http://localhost:9000"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    s3_bucket_name: str = "manga-images"
    s3_region: str = "us-east-1"

    # Scraper
    scraper_concurrent_browsers: int = Field(default=3, ge=1, le=10)
    scraper_request_delay_min: float = Field(default=1.0, ge=0.1)
    scraper_request_delay_max: float = Field(default=3.0, ge=0.5)
    scraper_max_retries: int = Field(default=3, ge=1, le=10)
    scraper_browser_timeout: int = Field(default=30000, ge=5000)

    # Rate Limits (per minute)
    rate_limit_default: int = 20
    rate_limit_asuracomic: int = 10
    rate_limit_manhwatop: int = 10
    rate_limit_mgeko: int = 30

    # Proxy
    proxy_url: str | None = None
    proxy_rotation_enabled: bool = False

    @computed_field
    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    def get_rate_limit(self, domain: str) -> int:
        """Get rate limit for specific domain."""
        limits = {
            "asuracomic.net": self.rate_limit_asuracomic,
            "manhwatop.com": self.rate_limit_manhwatop,
            "mgeko.cc": self.rate_limit_mgeko,
        }
        return limits.get(domain, self.rate_limit_default)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
