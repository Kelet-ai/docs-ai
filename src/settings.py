from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    port: int = 8001
    redis_url: str = "redis://localhost:6379"
    docs_llms_urls: str = "https://kelet.ai/llms.txt"
    docs_refresh_interval_seconds: int = 3600
    docs_ai_model: str = "bedrock:global.anthropic.claude-sonnet-4-6"
    rate_limit_messages_per_window: int = 20  # requests allowed per rate_limit_window_seconds
    rate_limit_window_seconds: int = 3600
    session_ttl_seconds: int = 1800

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False,
        extra="ignore",
    )


settings = Settings()

__all__ = ["settings"]
