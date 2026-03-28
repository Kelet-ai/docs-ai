"""Shared test fixtures."""
import pytest
import pytest_asyncio
from fakeredis.aioredis import FakeRedis

from docs_loader import DocsCache


@pytest.fixture
def sample_cache() -> DocsCache:
    """Pre-populated DocsCache with 2 test pages — no network calls."""
    cache = DocsCache()
    cache.pages = {
        "docs/getting-started/quickstart": (
            "# Quickstart\n## Installation\nInstall with pip:\n\n```bash\npip install kelet\n```\n\n"
            "## Usage\nImport and initialize the SDK."
        ),
        "docs/concepts/sessions": (
            "# Sessions\n## Overview\nA session tracks conversation state across multiple turns.\n\n"
            "## Session ID\nEach session has a unique ID used to correlate events."
        ),
    }
    cache.index_content = (
        "# Kelet Docs\n\n"
        "- [Quickstart](https://kelet.ai/docs/getting-started/quickstart.md): Quickstart Guide\n"
        "- [Sessions](https://kelet.ai/docs/concepts/sessions.md): Sessions\n"
    )
    cache._build_bm25_index()
    return cache


@pytest_asyncio.fixture
async def mock_redis():
    """Async fakeredis instance."""
    redis = FakeRedis(decode_responses=True)
    yield redis
    await redis.aclose()
