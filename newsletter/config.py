from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = Field(default="development", alias="APP_ENV")
    database_url: str = Field(default="sqlite:///./newsletter.db", alias="DATABASE_URL")
    object_store_root: Path = Field(default=Path("./var/object-store"), alias="OBJECT_STORE_ROOT")
    default_research_job_mode: str = Field(default="background", alias="DEFAULT_RESEARCH_JOB_MODE")
    firecrawl_api_key: str | None = Field(default=None, alias="FIRECRAWL_API_KEY")
    youtube_api_key: str | None = Field(default=None, alias="YOUTUBE_API_KEY")
    x_bearer_token: str | None = Field(default=None, alias="X_BEARER_TOKEN")

    zeroentropy_api_key: str | None = Field(default=None, alias="ZEROENTROPY_API_KEY")
    qdrant_url: str | None = Field(default=None, alias="QDRANT_URL")
    qdrant_api_key: str | None = Field(default=None, alias="QDRANT_API_KEY")
    qdrant_collection: str = Field(default="founders", alias="QDRANT_COLLECTION")

    exa_api_key: str | None = Field(default=None, alias="EXA_API_KEY")

    anthropic_api_key: str | None = Field(default=None, alias="ANTHROPIC_API_KEY")
    anthropic_model: str = Field(default="claude-sonnet-4-6", alias="ANTHROPIC_MODEL")
    anthropic_title_model: str = Field(default="claude-haiku-4-5-20251001", alias="ANTHROPIC_TITLE_MODEL")
    newsletter_model: str = Field(default="claude-opus-4-8", alias="NEWSLETTER_MODEL")
    mem0_api_key: str | None = Field(default=None, alias="MEM0_API_KEY")

    supabase_url: str | None = Field(default=None, alias="SUPABASE_URL")
    supabase_anon_key: str | None = Field(default=None, alias="SUPABASE_ANON_KEY")
    supabase_jwt_secret: str | None = Field(default=None, alias="SUPABASE_JWT_SECRET")

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    get_settings.cache_clear()

