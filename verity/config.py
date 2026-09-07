from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # Database
    database_url: str = "postgresql+asyncpg://verity:verity@localhost:5432/verity"
    database_url_sync: str = "postgresql://verity:verity@localhost:5432/verity"

    # Redis / Celery
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"

    # Companies House
    companies_house_api_key: str = ""
    companies_house_base_url: str = "https://api.company-information.service.gov.uk"

    # Anthropic
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-opus-4-5"

    # Polling
    poll_interval_seconds: int = 3600  # 1 hour default

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache
def get_settings() -> Settings:
    return Settings()
