"""Unit tests for Redis fixed-window rate limiter."""
import time

import pytest
from unittest.mock import patch

from rate_limiter import check_rate_limit


@pytest.mark.asyncio
async def test_rate_limit_allows_up_to_limit(mock_redis, monkeypatch):
    """20 requests pass, 21st is rejected."""
    monkeypatch.setattr("settings.settings.rate_limit_messages_per_window", 20)
    monkeypatch.setattr("settings.settings.rate_limit_window_seconds", 3600)

    for i in range(20):
        result = await check_rate_limit(mock_redis, "1.2.3.4")
        assert result is True, f"Request {i+1} should pass"

    result = await check_rate_limit(mock_redis, "1.2.3.4")
    assert result is False, "21st request should be rejected"


@pytest.mark.asyncio
async def test_rate_limit_resets_next_window(mock_redis, monkeypatch):
    """After window expires, counter resets and requests are allowed again."""
    monkeypatch.setattr("settings.settings.rate_limit_messages_per_window", 5)
    monkeypatch.setattr("settings.settings.rate_limit_window_seconds", 3600)

    for _ in range(5):
        await check_rate_limit(mock_redis, "2.3.4.5")

    # Depleted
    assert await check_rate_limit(mock_redis, "2.3.4.5") is False

    # Advance time by 1 full window
    future = time.time() + 3601
    with patch("rate_limiter.time.time", return_value=future):
        assert await check_rate_limit(mock_redis, "2.3.4.5") is True


@pytest.mark.asyncio
async def test_rate_limit_per_ip(mock_redis, monkeypatch):
    """Rate limit is per-IP; one IP exhausted doesn't affect another."""
    monkeypatch.setattr("settings.settings.rate_limit_messages_per_window", 2)
    monkeypatch.setattr("settings.settings.rate_limit_window_seconds", 3600)

    await check_rate_limit(mock_redis, "10.0.0.1")
    await check_rate_limit(mock_redis, "10.0.0.1")
    assert await check_rate_limit(mock_redis, "10.0.0.1") is False

    # Different IP unaffected
    assert await check_rate_limit(mock_redis, "10.0.0.2") is True
