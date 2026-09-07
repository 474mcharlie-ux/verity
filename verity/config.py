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

    # Hermes via Ollama (local — no data leaves the firm)
    ollama_base_url: str = "http://ollama:11434/v1"
    ollama_model: str = "nous-hermes2"   # or nous-hermes2:10.7b, nous-hermes2-mixtral

    # Anthropic (fallback / cloud option — review data handling with firm first)
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-opus-4-5"

    # Which backend to use: "ollama" | "anthropic"
    llm_backend: str = "ollama"

    # Polling
    poll_interval_seconds: int = 3600  # 1 hour default

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache
def get_settings() -> Settings:
    return Settings()
