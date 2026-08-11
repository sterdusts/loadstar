"""Central, environment-driven application configuration."""

from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration loaded from ``LN_*`` environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="LN_",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "Learning Navigator"
    database_url: str = "sqlite:///./learning_navigator.db"
    debug: bool = False
    auto_create_schema: bool = True
    ai_provider: str = "mock"
    ai_base_url: str = "http://localhost:11434/v1"
    ai_model: str = "mock-learning-map-v1"
    ai_api_key: SecretStr | None = None
    storage_secret: SecretStr = SecretStr("development-only-change-me")
    internal_api_url: str = "http://127.0.0.1:8000/api"
    mastery_required_level: int = Field(default=3, ge=0, le=5)
    review_after_days: int = Field(default=30, ge=1, le=3650)
    algorithm_version: str = "path-rule-v1"
    mastery_algorithm_version: str = "mastery-rule-v1"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide immutable settings object."""

    return Settings()
