"""Integration tests for POST /chat and GET /chat endpoints."""
import pytest
import pytest_asyncio
from contextlib import asynccontextmanager
from unittest.mock import patch
from httpx import AsyncClient, ASGITransport
from fakeredis.aioredis import FakeRedis


# --- Mock helpers ---
from pydantic_ai import PartDeltaEvent, PartStartEvent, TextPartDelta
from pydantic_ai.messages import TextPart


class _MockResult:
    output = "Hello world"

    def all_messages_json(self):
        return b"[]"


class _MockNode:
    def __init__(self, chunks):
        self._chunks = chunks

    def stream(self, ctx):
        chunks = self._chunks

        @asynccontextmanager
        async def _stream():
            async def _gen():
                first, *rest = chunks
                yield PartStartEvent(index=0, part=TextPart(content=first))
                for chunk in rest:
                    yield PartDeltaEvent(index=0, delta=TextPartDelta(content_delta=chunk))
            yield _gen()

        return _stream()


class _MockAgentRun:
    def __init__(self, nodes, result):
        self._nodes = iter(nodes)
        self.result = result

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._nodes)
        except StopIteration:
            raise StopAsyncIteration


def make_mock_iter(chunks=("Hello", " world"), raise_exc=None):
    @asynccontextmanager
    async def _mock(*args, **kwargs):
        if raise_exc:
            raise raise_exc
        node = _MockNode(chunks)
        yield _MockAgentRun(nodes=[node], result=_MockResult())
    return _mock


# --- Fixtures ---
@pytest_asyncio.fixture
async def redis():
    r = FakeRedis(decode_responses=True)
    yield r
    await r.aclose()


@pytest_asyncio.fixture
async def client(redis, sample_cache, monkeypatch):
    import app.main
    import docs_loader
    import routers.chat
    monkeypatch.setattr(docs_loader, "docs_cache", sample_cache)
    monkeypatch.setattr(routers.chat, "docs_cache", sample_cache)
    monkeypatch.setattr(app.main, "docs_cache", sample_cache)

    from app.main import app

    # Bypass lifespan by setting state directly
    app.state.redis = redis

    with patch("routers.chat.chat_agent.iter", new=make_mock_iter()), \
         patch("routers.chat.Agent.is_model_request_node", side_effect=lambda n: isinstance(n, _MockNode)):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c


# --- Tests ---
@pytest.mark.asyncio
async def test_health_returns_200_when_loaded(client):
    """Health endpoint returns 200 when Redis is up and docs are loaded."""
    resp = await client.get("/health")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_new_session_returns_session_id(client):
    resp = await client.post("/chat", json={"message": "what is a session?"})
    # Collect full SSE response
    assert resp.status_code == 200
    assert "X-Session-ID" in resp.headers
    sid = resp.headers["X-Session-ID"]
    assert len(sid) == 36  # UUID format


@pytest.mark.asyncio
async def test_message_too_long(client):
    resp = await client.post("/chat", json={"message": "x" * 4001})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_rate_limit_429(redis, sample_cache, monkeypatch):
    import app.main
    import docs_loader
    import routers.chat
    monkeypatch.setattr(docs_loader, "docs_cache", sample_cache)
    monkeypatch.setattr(routers.chat, "docs_cache", sample_cache)
    monkeypatch.setattr(app.main, "docs_cache", sample_cache)
    monkeypatch.setattr("settings.settings.rate_limit_messages_per_window", 3)
    monkeypatch.setattr("settings.settings.rate_limit_window_seconds", 3600)

    from app.main import app
    app.state.redis = redis

    with patch("routers.chat.chat_agent.iter", new=make_mock_iter()), \
         patch("routers.chat.Agent.is_model_request_node", side_effect=lambda n: isinstance(n, _MockNode)):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            for _ in range(3):
                r = await c.post("/chat", json={"message": "hi"})
                assert r.status_code == 200
            r = await c.post("/chat", json={"message": "hi"})
            assert r.status_code == 429


@pytest.mark.asyncio
async def test_expired_session_auto_creates(client, redis):
    """Unknown session_id silently creates a new session."""
    resp = await client.post("/chat", json={"message": "hi", "session_id": "nonexistent-id"})
    assert resp.status_code == 200
    new_sid = resp.headers.get("X-Session-ID")
    assert new_sid is not None
    assert new_sid != "nonexistent-id"


@pytest.mark.asyncio
async def test_current_page_slug_in_response(client):
    """current_page_slug in request doesn't break anything."""
    resp = await client.post("/chat", json={
        "message": "explain this",
        "current_page_slug": "concepts/sessions"
    })
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_agent_exception_yields_sse_error(redis, sample_cache, monkeypatch):
    """Agent exception → SSE error event, stream closes cleanly."""
    import app.main
    import docs_loader
    import routers.chat
    monkeypatch.setattr(docs_loader, "docs_cache", sample_cache)
    monkeypatch.setattr(routers.chat, "docs_cache", sample_cache)
    monkeypatch.setattr(app.main, "docs_cache", sample_cache)

    from app.main import app
    app.state.redis = redis

    with patch("routers.chat.chat_agent.iter", new=make_mock_iter(raise_exc=RuntimeError("model error"))), \
         patch("routers.chat.Agent.is_model_request_node", side_effect=lambda n: isinstance(n, _MockNode)):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post("/chat", json={"message": "hi"})
            assert resp.status_code == 200
            assert '"error"' in resp.text


@pytest.mark.asyncio
async def test_session_continuation(client, redis):
    """Second message with same session_id continues conversation."""
    r1 = await client.post("/chat", json={"message": "hello"})
    sid = r1.headers["X-Session-ID"]

    r2 = await client.post("/chat", json={"message": "and?", "session_id": sid})
    assert r2.status_code == 200


@pytest.mark.asyncio
async def test_get_chat_stateless(client):
    """GET /chat returns plain text — no session, no SSE envelope."""
    resp = await client.get("/chat", params={"q": "what is a session?"})
    assert resp.status_code == 200
    assert "X-Session-ID" not in resp.headers
    assert resp.headers["content-type"].startswith("text/plain")
    assert "data:" not in resp.text  # no SSE envelope
    assert "Hello" in resp.text


@pytest.mark.asyncio
async def test_get_chat_message_too_long(client):
    resp = await client.get("/chat", params={"q": "x" * 4001})
    assert resp.status_code == 422


