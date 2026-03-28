"""Unit tests for DocsCache."""
import asyncio

import pytest

from docs_loader import DocsCache, _parse_urls_from_llms, _tokenize, _url_to_key


def test_parse_urls_from_llms_classifies_correctly():
    content = (
        "# Kelet\n\n"
        "- [Docs index](https://kelet.ai/docs/llms.txt): Full docs\n"
        "- [Quickstart](https://kelet.ai/docs/getting-started/quickstart.md): Getting started\n"
        "- [Pricing](/pricing): Pricing page\n"
    )
    llms_urls, page_urls = _parse_urls_from_llms(content, "https://kelet.ai/llms.txt")
    assert "https://kelet.ai/docs/llms.txt" in llms_urls
    assert "https://kelet.ai/docs/getting-started/quickstart.md" in page_urls
    assert "https://kelet.ai/pricing" in page_urls  # relative path resolved


def test_parse_urls_from_llms_deduplication():
    content = (
        "- [A](https://kelet.ai/page.md): First\n"
        "- [B](https://kelet.ai/page.md): Second\n"
    )
    _, page_urls = _parse_urls_from_llms(content, "https://kelet.ai/llms.txt")
    assert page_urls.count("https://kelet.ai/page.md") == 1


def test_url_to_key_strips_md():
    assert _url_to_key("https://kelet.ai/docs/concepts/sessions.md") == "docs/concepts/sessions"


def test_url_to_key_no_md():
    assert _url_to_key("https://kelet.ai/pricing") == "pricing"


def test_tokenize():
    assert _tokenize("Hello World") == ["hello", "world"]


def test_search_returns_relevant_chunk(sample_cache):
    result = sample_cache.search("install kelet", top_k=2)
    assert "Installation" in result or "pip install" in result


def test_search_empty_query(sample_cache):
    result = sample_cache.search("", top_k=3)
    assert "Empty query" in result or "not" in result.lower()


def test_get_page_valid(sample_cache):
    content = sample_cache.get_page("docs/concepts/sessions")
    assert content is not None
    assert "session" in content.lower()


def test_get_page_invalid(sample_cache):
    assert sample_cache.get_page("nonexistent/page") is None


def test_build_bm25_index_chunks(sample_cache):
    """BM25 index has chunks from both pages."""
    assert len(sample_cache._chunks) >= 2
    assert sample_cache._bm25 is not None


@pytest.mark.asyncio
async def test_start_retries_on_timeout(monkeypatch):
    """start() retries 3 times then raises on persistent fetch failure."""
    call_count = 0

    async def failing_fetch(self):
        nonlocal call_count
        call_count += 1
        raise asyncio.TimeoutError("timeout")

    monkeypatch.setattr(DocsCache, "_fetch_all", failing_fetch)
    cache = DocsCache()
    with pytest.raises(RuntimeError, match="3 attempts"):
        await cache.start()
    assert call_count == 3


@pytest.mark.asyncio
async def test_refresh_loop_preserves_stale_content_on_error(monkeypatch, sample_cache):
    """_refresh_loop swallows fetch errors and keeps stale content."""
    original_content = sample_cache.index_content

    async def failing_fetch(self):
        raise Exception("network error")

    monkeypatch.setattr(DocsCache, "_fetch_all", failing_fetch)
    monkeypatch.setattr("settings.settings.docs_refresh_interval_seconds", 0)

    task = asyncio.create_task(sample_cache._refresh_loop())
    await asyncio.sleep(0.05)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert sample_cache.index_content == original_content
