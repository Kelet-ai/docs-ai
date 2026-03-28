"""pydantic-ai Agent for docs Q&A. Tools injected via DocsDeps."""
from dataclasses import dataclass
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, Template
from pydantic_ai import Agent, RunContext
from pydantic_ai.settings import ModelSettings

from docs_loader import DocsCache
from settings import settings

_jinja_env = Environment(
    loader=FileSystemLoader(Path(__file__).parent / "prompts"),
    autoescape=False,  # Markdown prompts for LLM — not HTML, no escaping needed
)
_chat_template: Template = _jinja_env.get_template("chat_system.j2")


@dataclass
class DocsDeps:
    cache: DocsCache                           # injected — enables isolated testing
    index_content: str                         # llms.txt for system prompt
    current_page_slug: str | None = None       # page user is currently viewing
    stateless: bool = False                    # True for GET /chat — no follow-up possible


chat_agent: Agent[DocsDeps, str] = Agent(
    model=settings.docs_ai_model,
    output_type=str,
    deps_type=DocsDeps,
    model_settings=ModelSettings(temperature=0.2),
)


@chat_agent.system_prompt
def _system_prompt(ctx: RunContext[DocsDeps]) -> str:
    return _chat_template.render(
        index_content=ctx.deps.index_content,
        current_page_slug=ctx.deps.current_page_slug,
        stateless=ctx.deps.stateless,
    )


@chat_agent.tool
def search_docs(ctx: RunContext[DocsDeps], query: str) -> str:
    """Search documentation with BM25. Use when unsure which page covers the topic."""
    return ctx.deps.cache.search(query, top_k=3)


@chat_agent.tool
def get_page(ctx: RunContext[DocsDeps], slug: str) -> str:
    """Get full content of a doc page by slug.
    Slugs are the URL path without the domain and without the .md extension.
    e.g. https://kelet.ai/docs/concepts/sessions.md -> 'docs/concepts/sessions'
         https://kelet.ai/pricing -> 'pricing'
    Use the index in your system prompt to identify the right slug.
    """
    content = ctx.deps.cache.get_page(slug)
    return content if content else f"Page '{slug}' not found. Available slugs are listed in the docs index."
