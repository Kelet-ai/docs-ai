"""FastAPI application — docs-ai service."""
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from redis.asyncio import Redis
from redis.asyncio import from_url as redis_from_url

from docs_loader import docs_cache
from routers.chat import router as chat_router
from settings import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    redis = await redis_from_url(settings.redis_url, decode_responses=True)
    await redis.ping()  # type: ignore[misc]  # fail fast if Redis is unreachable
    app.state.redis = redis
    await docs_cache.start()
    try:
        yield
    finally:
        await docs_cache.stop()
        await redis.aclose()


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
