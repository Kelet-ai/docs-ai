"""DocsCache: BFS-fetches llms.txt files and their linked pages, builds BM25 index in memory."""
import asyncio
import logging
import re
from collections import deque
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

import httpx
from rank_bm25 import BM25Okapi

from settings import settings

logger = logging.getLogger(__name__)


def _parse_urls_from_llms(content: str, base_url: str) -> tuple[list[str], list[str]]:
    """Parse llms.txt content — classify markdown-link URLs as nested llms.txt or content pages.

    Returns (nested_llms_urls, page_urls) as absolute URLs.
    base_url is used to resolve relative paths.
    """
    llms_urls: list[str] = []
    page_urls: list[str] = []
    seen: set[str] = set()

    for raw_url in re.findall(r'\[[^\]]*\]\(([^)]+)\)', content):
        raw_url = raw_url.strip().split('#')[0]
        if not raw_url:
            continue
        abs_url = urljoin(base_url, raw_url)
        if abs_url in seen:
            continue
        seen.add(abs_url)

        if abs_url.endswith('llms.txt'):
            llms_urls.append(abs_url)
        else:
            page_urls.append(abs_url)

    return llms_urls, page_urls


def _url_to_key(url: str) -> str:
    """Convert a page URL to a cache key: path without leading slash, strip .md suffix."""
    path = urlparse(url).path.lstrip('/')
    if path.endswith('.md'):
        path = path[:-3]
    return path


def _tokenize(text: str) -> list[str]:
    return re.findall(r'\w+', text.lower())


async def _fetch_page(client: httpx.AsyncClient, url: str) -> tuple[str, str] | None:
    """Fetch a single page. Returns (slug, content) or None on failure."""
    try:
        r = await client.get(url, timeout=15.0)
        if r.status_code == 200 and r.text.strip():
            return _url_to_key(url), r.text
    except Exception as e:
        logger.warning("Failed to fetch page %s: %s", url, e)
    return None


@dataclass
class DocsCache:
    index_content: str = ""
    pages: dict[str, str] = field(default_factory=dict)
    _chunks: list[dict[str, str]] = field(default_factory=list)
    _bm25: BM25Okapi | None = field(default=None, init=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)
    _refresh_task: asyncio.Task | None = field(default=None, init=False)

    async def start(self) -> None:
        """Load docs with retry. 3 attempts x 30s timeout, 2s backoff. Raises on 3rd failure."""
        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                await asyncio.wait_for(self._fetch_all(), timeout=30.0)
                self._refresh_task = asyncio.create_task(self._refresh_loop())
                return
            except Exception as e:
                last_exc = e
                if attempt < 2:
                    await asyncio.sleep(2.0)
        raise RuntimeError(f"Failed to load docs after 3 attempts: {last_exc}") from last_exc

    async def stop(self) -> None:
        if self._refresh_task:
            self._refresh_task.cancel()
            try:
                await self._refresh_task
            except asyncio.CancelledError:
                pass

    async def _fetch_all(self) -> None:
        """BFS over llms.txt files starting from settings.docs_llms_urls."""
        initial_urls = settings.docs_llms_urls.split()

        async with httpx.AsyncClient(follow_redirects=True) as client:
            queue: deque[str] = deque(initial_urls)
            visited_llms: set[str] = set()
            seen_page_urls: set[str] = set()
            all_page_urls: list[str] = []
            all_index_parts: list[str] = []

            while queue:
                llms_url = queue.popleft()
                if llms_url in visited_llms:
                    continue
                visited_llms.add(llms_url)

                try:
                    resp = await client.get(llms_url, timeout=20.0)
                    resp.raise_for_status()
                    content = resp.text
                except Exception as e:
                    logger.warning("Failed to fetch %s: %s", llms_url, e)
                    continue  # Skip failed llms.txt fetches; others may still succeed

                all_index_parts.append(content)
                nested_llms, page_urls = _parse_urls_from_llms(content, llms_url)

                for url in nested_llms:
                    if url not in visited_llms:
                        queue.append(url)

                for url in page_urls:
                    if url not in seen_page_urls:
                        seen_page_urls.add(url)
                        all_page_urls.append(url)

            # Fetch pages concurrently, bounded to avoid hammering the docs server (20 parallel fetches)
            sem = asyncio.Semaphore(20)

            async def _bounded(url: str) -> tuple[str, str] | None:
                async with sem:
                    return await _fetch_page(client, url)

            results = await asyncio.gather(*[_bounded(url) for url in all_page_urls])
            pages: dict[str, str] = {}
            for result in results:
                if result is not None:
                    slug, content = result
                    pages[slug] = content

        if not pages and not all_index_parts:
            raise RuntimeError("All llms.txt fetches failed — no docs loaded")
        if not pages:
            logger.warning("All page fetches failed — index text loaded but no searchable content")

        async with self._lock:
            self.index_content = '\n\n---\n\n'.join(all_index_parts)
            self.pages = pages
            self._build_bm25_index()

    async def _refresh_loop(self) -> None:
        while True:
            await asyncio.sleep(settings.docs_refresh_interval_seconds)
            try:
                await asyncio.wait_for(self._fetch_all(), timeout=30.0)
            except Exception as e:
                logger.warning("Docs refresh failed, keeping stale content: %s", e)

    def _build_bm25_index(self) -> None:
        """Build BM25 index from pages. Called after fetch (under lock). Also exposed for test fixtures."""
        chunks = []
        for slug, content in self.pages.items():
            sections = re.split(r'(?m)^(?=#{1,3} )', content)
            for section in sections:
                if not section.strip():
                    continue
                lines = section.strip().splitlines()
                heading = lines[0].lstrip('#').strip() if lines else slug
                body = '\n'.join(lines[1:]).strip()
                if body:
                    chunks.append({'slug': slug, 'heading': heading, 'content': body})

        if chunks:
            corpus = [_tokenize(c['content']) for c in chunks]
            self._bm25 = BM25Okapi(corpus)
        self._chunks = chunks

    def search(self, query: str, top_k: int = 3) -> str:
        """BM25 search. Snapshot refs before use — no await in this method means _fetch_all
        cannot swap _bm25/_chunks mid-call (single-threaded asyncio cooperative scheduling)."""
        bm25 = self._bm25
        chunks = self._chunks
        if bm25 is None or not chunks:
            return "Documentation not yet loaded."

        tokens = _tokenize(query)
        if not tokens:
            return "Empty query."

        scores = bm25.get_scores(tokens)
        top_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:top_k]

        results = []
        for i in top_indices:
            if scores[i] <= 0:
                continue
            c = chunks[i]
            results.append(f"## [{c['slug']}] {c['heading']}\n{c['content'][:800]}")

        return '\n\n---\n\n'.join(results) if results else "No relevant documentation found."

    @property
    def is_loaded(self) -> bool:
        return self._bm25 is not None

    def get_page(self, slug: str) -> str | None:
        return self.pages.get(slug)


# Module-level singleton — initialized in lifespan
docs_cache = DocsCache()
