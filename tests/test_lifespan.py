"""Tests for app lifespan — verifies in-memory fallback when REDIS_URL is not set."""
import pytest
from unittest.mock import AsyncMock
from fakeredis.aioredis import FakeRedis as InMemoryRedis


def test_redis_url_default_is_none(monkeypatch):
    """Settings.redis_url must default to None so the in-memory fallback activates out of the box."""
    monkeypatch.delenv("REDIS_URL", raising=False)
    from settings import Settings
    # Use _env_file=None to test the code default, independent of any local .env file
    assert Settings(_env_file=None).redis_url is None  # type: ignore[call-arg]


@pytest.mark.asyncio
async def test_lifespan_uses_inmemory_when_no_redis_url(monkeypatch, sample_cache):
    """When REDIS_URL is unset, lifespan sets app.state.redis to FakeRedis (in-memory)."""
    import app.main as main_module
    import docs_loader
    import routers.chat

    monkeypatch.setattr(docs_loader, "docs_cache", sample_cache)
    monkeypatch.setattr(routers.chat, "docs_cache", sample_cache)
    monkeypatch.setattr(main_module, "docs_cache", sample_cache)
    monkeypatch.setattr(main_module.settings, "redis_url", None)
    # sample_cache is already fully loaded; mock start/stop to skip network calls
    monkeypatch.setattr(sample_cache, "start", AsyncMock())
    monkeypatch.setattr(sample_cache, "stop", AsyncMock())

    from app.main import app, lifespan

    async with lifespan(app):
        assert isinstance(app.state.redis, InMemoryRedis)
