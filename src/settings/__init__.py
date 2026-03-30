from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    port: int = 8001
    host: str = "0.0.0.0"
    redis_url: str | None = None  # if unset, falls back to in-memory (single-process, not persistent)
    docs_llms_urls: str = ""
    docs_allowed_hosts: str = ""
    docs_refresh_interval_seconds: int = 3600
    docs_ai_model: str = "bedrock:global.anthropic.claude-sonnet-4-6"
    rate_limit_messages_per_window: int = 20  # requests allowed per rate_limit_window_seconds
    rate_limit_window_seconds: int = 3600
    session_ttl_seconds: int = 1800
    docs_allowed_topics: str = "scanned docs"
    docs_custom_instructions: str = ""
    docs_system_prompt_file: str = ""
    kelet_project: str = "docs_ai"
    kelet_api_key: str | None = None

    @field_validator("docs_custom_instructions")
    @classmethod
    def strip_custom_instructions(cls, v: str) -> str:
        return v.strip()

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False,
        extra="ignore",
    )


settings = Settings()

__all__ = ["settings"]
