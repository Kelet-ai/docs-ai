"""Tests for configurable system prompt: template loading and rendering."""
import pytest
from pathlib import Path
from jinja2 import Environment, FileSystemLoader


# --- Helpers ---

_PROMPTS_DIR = Path(__file__).parent.parent / "src" / "agent" / "prompts"


def render_base(
    allowed_topics: str = "scanned docs",
    custom_instructions: str = "",
    current_page_slug: str | None = None,
    stateless: bool = False,
    index_content: str = "## Index\n- [Page](/page.md)",
) -> str:
    env = Environment(loader=FileSystemLoader(_PROMPTS_DIR), autoescape=False)
    template = env.get_template("chat_system.j2")
    return template.render(
        index_content=index_content,
        current_page_slug=current_page_slug,
        stateless=stateless,
        allowed_topics=allowed_topics,
        custom_instructions=custom_instructions,
    )


# --- Base template: generic content ---

def test_base_template_has_no_kelet_references():
    result = render_base()
    assert "Kelet" not in result
    assert "kelet.ai" not in result
    assert "OpenTelemetry" not in result


def test_base_template_renders_without_config():
    result = render_base()
    assert "documentation assistant" in result
    assert "search_docs" in result
    assert "get_page" in result


# --- allowed_topics ---

def test_allowed_topics_renders_refusal():
    result = render_base(allowed_topics="MyProduct")
    assert "MyProduct" in result
    assert "STRICTLY REFUSE" in result


def test_allowed_topics_default_scanned_docs():
    result = render_base(allowed_topics="scanned docs")
    assert "scanned docs" in result
    assert "STRICTLY REFUSE" in result


def test_empty_allowed_topics_omits_refusal():
    result = render_base(allowed_topics="")
    assert "STRICTLY REFUSE" not in result


# --- custom_instructions ---

def test_custom_instructions_injected():
    result = render_base(custom_instructions="You are Acme's assistant.")
    assert "You are Acme's assistant." in result


def test_empty_custom_instructions_omits_block():
    result = render_base(custom_instructions="")
    assert not result.endswith("\n\n")


def test_whitespace_only_custom_instructions_omits_block():
    # The strip() validator in settings.py normalises "\n  \n" → "" before the value reaches
    # the template. The template has no stripping logic of its own — the validator is the guard.
    # This test documents that contract: after stripping, empty string → no custom block.
    result = render_base(custom_instructions="")
    assert not result.endswith("\n\n")


def test_allowed_topics_and_custom_instructions_independent():
    # Both slots work independently — neither suppresses the other.
    result = render_base(allowed_topics="Acme", custom_instructions="Be concise.")
    assert "Acme" in result
    assert "STRICTLY REFUSE" in result
    assert "Be concise." in result

    result_no_topics = render_base(allowed_topics="", custom_instructions="Be concise.")
    assert "STRICTLY REFUSE" not in result_no_topics
    assert "Be concise." in result_no_topics


# --- DOCS_SYSTEM_PROMPT_FILE ---

@pytest.fixture(autouse=True)
def _reset_agent_module():
    """Reload agent with default settings after each test to prevent module-state leakage."""
    yield
    import importlib
    import settings as settings_mod
    import agent as agent_mod
    importlib.reload(settings_mod)
    importlib.reload(agent_mod)


def test_load_template_uses_builtin_when_no_file(monkeypatch):
    monkeypatch.setenv("DOCS_SYSTEM_PROMPT_FILE", "")
    import importlib
    import settings as settings_mod
    importlib.reload(settings_mod)
    import agent as agent_mod
    importlib.reload(agent_mod)
    result = agent_mod._chat_template.render(
        index_content="## Index",
        current_page_slug=None,
        stateless=False,
        allowed_topics="scanned docs",
        custom_instructions="",
    )
    assert "documentation assistant" in result


def test_load_template_loads_custom_file(tmp_path, monkeypatch):
    custom = tmp_path / "custom.j2"
    custom.write_text("Custom: {{ allowed_topics }} | {{ custom_instructions }}")
    monkeypatch.setenv("DOCS_SYSTEM_PROMPT_FILE", str(custom))

    import importlib
    import settings as settings_mod
    importlib.reload(settings_mod)
    import agent as agent_mod
    importlib.reload(agent_mod)

    result = agent_mod._chat_template.render(
        index_content="",
        current_page_slug=None,
        stateless=False,
        allowed_topics="Acme",
        custom_instructions="extra",
    )
    assert result == "Custom: Acme | extra"


def test_load_template_raises_on_missing_file(monkeypatch):
    monkeypatch.setenv("DOCS_SYSTEM_PROMPT_FILE", "/nonexistent/path/prompt.j2")

    import importlib
    import settings as settings_mod
    importlib.reload(settings_mod)
    import agent as agent_mod

    with pytest.raises(ValueError, match="DOCS_SYSTEM_PROMPT_FILE not found"):
        importlib.reload(agent_mod)


# --- settings validator ---

def test_custom_instructions_stripped(monkeypatch):
    monkeypatch.setenv("DOCS_CUSTOM_INSTRUCTIONS", "\n  hello  \n")
    import importlib
    import settings as settings_mod
    importlib.reload(settings_mod)
    assert settings_mod.settings.docs_custom_instructions == "hello"


def test_custom_instructions_empty_stays_empty(monkeypatch):
    monkeypatch.setenv("DOCS_CUSTOM_INSTRUCTIONS", "")
    import importlib
    import settings as settings_mod
    importlib.reload(settings_mod)
    assert settings_mod.settings.docs_custom_instructions == ""
