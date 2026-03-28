"""Redis fixed-window rate limiter. INCR is atomic — safe for multi-replica deployments."""
import time

from redis.asyncio import Redis

from settings import settings

_RL_PREFIX = "docs-ai:rl:"


async def check_rate_limit(redis: Redis, ip: str) -> bool:
    """Return True if the request is allowed, False if rate limit exceeded.

    Uses a fixed-window counter keyed by (ip, window_id). INCR is atomic in Redis,
    so there is no read-modify-write race condition under concurrent requests.
    """
    window = settings.rate_limit_window_seconds
    limit = settings.rate_limit_messages_per_window
    window_id = int(time.time()) // window
    key = f"{_RL_PREFIX}{ip}:{window_id}"
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, window * 2)  # 2× window ensures key outlives the window
    return count <= limit
