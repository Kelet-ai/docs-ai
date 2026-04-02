"""Chat endpoints — POST /chat (session, SSE) and GET /chat (stateless, plain text)."""
import json
import logging
from typing import AsyncGenerator

import kelet
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field
from pydantic_ai import Agent, PartDeltaEvent, PartStartEvent, TextPartDelta
from pydantic_ai.messages import ModelMessage, ModelMessagesTypeAdapter, TextPart
from redis.asyncio import Redis

from agent import chat_agent, DocsDeps
from cache import ChatSession, create_session, get_session, save_session
from docs_loader import docs_cache
from rate_limiter import check_rate_limit
from settings import settings

logger = logging.getLogger(__name__)
router = APIRouter()


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    session_id: str | None = None
    current_page_slug: str | None = None


_REPHRASE_PREFIXES = (
    "actually,", "i meant", "no,", "wait,",
    "that's wrong", "that is wrong", "you're wrong",
    "not what i asked", "actually i",
)


async def _run_agent_stream(
    message: str,
    deps: DocsDeps,
    message_history: list[ModelMessage],
    session: ChatSession,
    redis: Redis,
) -> AsyncGenerator[str, None]:
    """SSE generator with session persistence."""
    is_rephrase = message.lower().startswith(_REPHRASE_PREFIXES) and bool(message_history)

    async with kelet.agentic_session(session_id=session.session_id):
        if is_rephrase and settings.kelet_api_key:
            try:
                await kelet.signal(
                    kind=kelet.SignalKind.FEEDBACK,
                    source=kelet.SignalSource.HUMAN,
                    trigger_name="user-correction",
                    score=0.0,
                )
            except Exception:
                logger.warning("Failed to emit user-correction signal", exc_info=True)

        messages_json: str | None = None
        try:
            async with chat_agent.iter(
                message, deps=deps, message_history=message_history
            ) as run:
                emitted_text = False
                async for node in run:
                    if Agent.is_model_request_node(node):
                        if emitted_text:
                            yield f"data: {json.dumps({'bubble_break': True})}\n\n"
                        async with node.stream(run.ctx) as stream:
                            async for event in stream:
                                if isinstance(event, PartStartEvent) and isinstance(event.part, TextPart):
                                    if event.part.content:
                                        yield f"data: {json.dumps({'chunk': event.part.content})}\n\n"
                                        emitted_text = True
                                elif isinstance(event, PartDeltaEvent) and isinstance(event.delta, TextPartDelta):
                                    yield f"data: {json.dumps({'chunk': event.delta.content_delta})}\n\n"
                                    emitted_text = True
                if run.result is not None:
                    messages_json = run.result.all_messages_json().decode()
        except Exception:
            logger.exception("Agent stream error")
            yield f"data: {json.dumps({'error': 'An error occurred. Please try again.'})}\n\n"
            return

        if messages_json is not None:
            try:
                session.history = messages_json
                await save_session(redis, session, settings.session_ttl_seconds)
            except Exception:
                logger.warning("Failed to persist session %s", session.session_id, exc_info=True)
        yield "data: [DONE]\n\n"


@router.get("/chat")
async def chat_stateless(
    request: Request,
    q: str = Query(min_length=1, max_length=4000),
) -> PlainTextResponse:
    """Stateless one-shot query — plain text response. No session, no history. Useful for curl / kelet skill."""
    redis: Redis = request.app.state.redis

    # request.client.host is resolved by uvicorn from X-Forwarded-For when
    # --proxy-headers is set and UVICORN_FORWARDED_ALLOW_IPS is configured.
    # request.client is always set behind uvicorn with --proxy-headers + UVICORN_FORWARDED_ALLOW_IPS.
    # Fallback to "unknown" groups all unresolved clients in one bucket — acceptable for this use case.
    client_ip = request.client.host if request.client else "unknown"
    if not await check_rate_limit(redis, client_ip):
        raise HTTPException(status_code=429, detail="Rate limit exceeded. Try again later.")

    deps = DocsDeps(
        cache=docs_cache,
        index_content=docs_cache.index_content,
        stateless=True,
    )

    async with chat_agent.iter(q, deps=deps) as run:
        async for _ in run:
            pass
        result = run.result
        output = result.output if result is not None else ""
    return PlainTextResponse(output)


@router.post("/chat", response_model=None)
async def chat(request: Request, body: ChatRequest) -> StreamingResponse:
    redis: Redis = request.app.state.redis

    client_ip = request.client.host if request.client else "unknown"
    if not await check_rate_limit(redis, client_ip):
        raise HTTPException(status_code=429, detail="Rate limit exceeded. Try again later.")

    # Session resolve — auto-create on missing/expired (no 404)
    session: ChatSession | None = None
    if body.session_id:
        session = await get_session(redis, body.session_id)
    if session is None:
        session = await create_session(redis, settings.session_ttl_seconds)

    message_history = ModelMessagesTypeAdapter.validate_json(session.history)

    deps = DocsDeps(
        cache=docs_cache,
        index_content=docs_cache.index_content,
        current_page_slug=body.current_page_slug,
    )

    return StreamingResponse(
        _run_agent_stream(body.message, deps, message_history, session, redis),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "X-Session-ID": session.session_id,
        },
    )
