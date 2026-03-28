"""Redis ChatSession CRUD for docs-ai. No org/project scope (public service)."""
import json
import uuid
from dataclasses import dataclass, field

from redis.asyncio import Redis

_SESSION_PREFIX = "docs-ai:session:"


def _key(session_id: str) -> str:
    return f"{_SESSION_PREFIX}{session_id}"


@dataclass
class ChatSession:
    session_id: str
    history: str = field(default_factory=lambda: "[]")  # pydantic-ai messages_json


async def create_session(redis: Redis, ttl: int) -> ChatSession:
    session_id = str(uuid.uuid4())
    session = ChatSession(session_id=session_id)
    await save_session(redis, session, ttl)
    return session


async def get_session(redis: Redis, session_id: str) -> ChatSession | None:
    raw = await redis.get(_key(session_id))
    if raw is None:
        return None
    data = json.loads(raw)
    return ChatSession(session_id=data["session_id"], history=data.get("history", "[]"))


async def save_session(redis: Redis, session: ChatSession, ttl: int) -> None:
    await redis.setex(
        _key(session.session_id),
        ttl,
        json.dumps({"session_id": session.session_id, "history": session.history}),
    )
