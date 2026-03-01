# tests/test_knowledge/test_demo_knowledge.py
"""Tests for the demo knowledge base and KnowledgeManager local_dir backend."""

import pytest
from pathlib import Path

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

DEMO_DIR = Path(__file__).parent.parent.parent / "examples" / "demo_knowledge"

EXPECTED_FILES = [
    "python_tips.md",
    "git_commands.md",
    "agent_glossary.md",
]

# ---------------------------------------------------------------------------
# File existence and content tests
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("filename", EXPECTED_FILES)
def test_demo_file_exists(filename: str) -> None:
    """Each demo knowledge file must exist in the demo_knowledge directory."""
    path = DEMO_DIR / filename
    assert path.exists(), f"Missing demo knowledge file: {path}"


@pytest.mark.parametrize("filename", EXPECTED_FILES)
def test_demo_file_is_non_empty(filename: str) -> None:
    """Each demo knowledge file must contain non-trivial content (>50 bytes)."""
    path = DEMO_DIR / filename
    content = path.read_text(encoding="utf-8")
    assert len(content) > 50, f"File {filename} is too short ({len(content)} bytes)"


def test_python_tips_content() -> None:
    """python_tips.md must mention Python best practices keywords."""
    content = (DEMO_DIR / "python_tips.md").read_text(encoding="utf-8").lower()
    assert "python" in content
    # At least one of the core topics should be mentioned
    assert any(kw in content for kw in ("type hint", "pep", "f-string", "docstring", "virtual")), \
        "python_tips.md does not mention expected best-practice topics"


def test_git_commands_content() -> None:
    """git_commands.md must mention at least 3 git command names."""
    content = (DEMO_DIR / "git_commands.md").read_text(encoding="utf-8").lower()
    git_cmds = ["git init", "git clone", "git add", "git commit", "git push", "git pull", "git log"]
    found = [cmd for cmd in git_cmds if cmd in content]
    assert len(found) >= 3, f"Only found {len(found)} git commands in git_commands.md: {found}"


def test_agent_glossary_content() -> None:
    """agent_glossary.md must define Agent, Tool, MCP, Knowledge Base, and Sub-Agent."""
    content = (DEMO_DIR / "agent_glossary.md").read_text(encoding="utf-8").lower()
    required_terms = ["agent", "tool", "mcp", "knowledge base", "sub-agent"]
    for term in required_terms:
        assert term in content, f"agent_glossary.md is missing definition for: {term}"


# ---------------------------------------------------------------------------
# KnowledgeManager instantiation test
# ---------------------------------------------------------------------------

def test_knowledge_manager_instantiates_with_local_dir() -> None:
    """KnowledgeManager must accept a local_dir KnowledgeSourceSpec without error."""
    from everstaff.schema.agent_spec import KnowledgeSourceSpec
    from everstaff.knowledge.manager import KnowledgeManager

    spec = KnowledgeSourceSpec(type="local_dir", path=str(DEMO_DIR))
    manager = KnowledgeManager(sources=[spec])
    assert manager.has_backends, "KnowledgeManager should have at least one backend"


def test_knowledge_manager_has_no_backends_for_empty_sources() -> None:
    """KnowledgeManager with no sources must report has_backends == False."""
    from everstaff.knowledge.manager import KnowledgeManager

    manager = KnowledgeManager(sources=[])
    assert not manager.has_backends


# ---------------------------------------------------------------------------
# get_prompt_injection test
# ---------------------------------------------------------------------------

def test_get_prompt_injection_is_non_empty() -> None:
    """get_prompt_injection() must return a non-empty string when backends exist."""
    from everstaff.schema.agent_spec import KnowledgeSourceSpec
    from everstaff.knowledge.manager import KnowledgeManager

    spec = KnowledgeSourceSpec(type="local_dir", path=str(DEMO_DIR))
    manager = KnowledgeManager(sources=[spec])
    injection = manager.get_prompt_injection()
    assert injection, "get_prompt_injection() returned empty string"
    assert len(injection) > 20, "get_prompt_injection() text is unexpectedly short"


def test_get_prompt_injection_contains_knowledge_base_header() -> None:
    """get_prompt_injection() output must contain the '## Knowledge Base' header."""
    from everstaff.schema.agent_spec import KnowledgeSourceSpec
    from everstaff.knowledge.manager import KnowledgeManager

    spec = KnowledgeSourceSpec(type="local_dir", path=str(DEMO_DIR))
    manager = KnowledgeManager(sources=[spec])
    injection = manager.get_prompt_injection()
    assert "Knowledge Base" in injection, \
        f"Expected 'Knowledge Base' in injection text, got: {injection!r}"


def test_get_prompt_injection_references_demo_dir() -> None:
    """get_prompt_injection() must reference the local_dir path so the agent knows where to look."""
    from everstaff.schema.agent_spec import KnowledgeSourceSpec
    from everstaff.knowledge.manager import KnowledgeManager

    spec = KnowledgeSourceSpec(type="local_dir", path=str(DEMO_DIR))
    manager = KnowledgeManager(sources=[spec])
    injection = manager.get_prompt_injection()
    # The backend stores the resolved absolute path, so the last component is always present
    assert "demo_knowledge" in injection, \
        f"Expected demo_knowledge path segment in injection text, got: {injection!r}"


def test_get_prompt_injection_empty_for_no_backends() -> None:
    """get_prompt_injection() must return empty string when there are no backends."""
    from everstaff.knowledge.manager import KnowledgeManager

    manager = KnowledgeManager(sources=[])
    assert manager.get_prompt_injection() == ""


# ---------------------------------------------------------------------------
# Async search test
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_search_returns_results_for_known_term() -> None:
    """search() must return at least one result for a term present in the demo files."""
    from everstaff.schema.agent_spec import KnowledgeSourceSpec
    from everstaff.knowledge.manager import KnowledgeManager

    spec = KnowledgeSourceSpec(type="local_dir", path=str(DEMO_DIR))
    manager = KnowledgeManager(sources=[spec])

    result = await manager.search("python")
    assert result.total_found > 0, "Expected at least one result for query 'python'"
    assert result.chunks, "Expected non-empty chunks list"


@pytest.mark.asyncio
async def test_search_chunks_contain_query_term() -> None:
    """search() results for 'git' should include content from git_commands.md."""
    from everstaff.schema.agent_spec import KnowledgeSourceSpec
    from everstaff.knowledge.manager import KnowledgeManager

    spec = KnowledgeSourceSpec(type="local_dir", path=str(DEMO_DIR))
    manager = KnowledgeManager(sources=[spec])

    result = await manager.search("git commit")
    sources = [chunk.source for chunk in result.chunks]
    assert any("git_commands" in src for src in sources), \
        f"Expected git_commands.md in results, got sources: {sources}"


def test_knowledge_manager_get_tools_returns_search_and_get_doc():
    """get_tools() must return search_knowledge and get_knowledge_document tools."""
    from everstaff.schema.agent_spec import KnowledgeSourceSpec
    from everstaff.knowledge.manager import KnowledgeManager

    spec = KnowledgeSourceSpec(type="local_dir", path=str(DEMO_DIR))
    manager = KnowledgeManager(sources=[spec])
    tools = manager.get_tools()

    tool_names = {t.definition.name for t in tools}
    assert "search_knowledge" in tool_names
    assert "get_knowledge_document" in tool_names


def test_knowledge_manager_get_tools_empty_when_no_backends():
    """get_tools() must return [] when there are no backends."""
    from everstaff.knowledge.manager import KnowledgeManager

    manager = KnowledgeManager(sources=[])
    assert manager.get_tools() == []
