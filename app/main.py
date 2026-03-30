"""FastAPI application — docs-ai service."""
import logging
from contextlib import asynccontextmanager

import kelet
from fakeredis.aioredis import FakeRedis as InMemoryRedis  # in-memory fallback; alias clarifies prod intent
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from redis.asyncio import Redis
from redis.asyncio import from_url as redis_from_url

from docs_loader import docs_cache
from routers.chat import router as chat_router
from settings import settings

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.redis_url is None:
        # No REDIS_URL configured: use in-memory store (single-process, not persistent).
        # FakeRedis has no maxsize cap; TTLs provide natural eviction
        # (sessions: 30 min, rate-limit keys: 2 h by default).
        logger.info("store: in-memory (REDIS_URL not set) — data is not persistent and not shared across replicas")
        redis = InMemoryRedis(decode_responses=True)
    else:
        from urllib.parse import urlparse
        _p = urlparse(settings.redis_url)
        logger.info("store: Redis at %s:%s", _p.hostname, _p.port)
        redis = await redis_from_url(settings.redis_url, decode_responses=True)
        await redis.ping()  # type: ignore[misc]  # fail fast if Redis is unreachable
    app.state.redis = redis
    if settings.kelet_api_key:
        kelet.configure(api_key=settings.kelet_api_key, project=settings.kelet_project)
    await docs_cache.start()
    try:
        yield
    finally:
        await docs_cache.stop()
        await redis.aclose()
        if settings.kelet_api_key:
            kelet.shutdown()  # flush BatchSpanProcessor before process exits


app = FastAPI(title="Docs AI", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # intentionally public — kelet skill + any browser origin
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
    expose_headers=["X-Session-ID"],  # REQUIRED: browser can't read header without this
)

app.include_router(chat_router)


@app.get("/health")
async def health(request: Request):
    redis: Redis = request.app.state.redis
    await redis.ping()  # type: ignore[misc]
    if not docs_cache.is_loaded:
        raise HTTPException(status_code=503, detail="docs not yet loaded")
    return {"status": "ok"}
