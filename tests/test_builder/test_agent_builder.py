import pytest
from unittest.mock import AsyncMock, MagicMock


def make_minimal_spec():
    from everstaff.schema.agent_spec import AgentSpec
    import yaml, textwrap
    raw = textwrap.dedent("""
        agent_name: test-agent
        instructions: You are a test agent.
        tools: []
        skills: []
    """)
    return AgentSpec.model_validate(yaml.safe_load(raw))


@pytest.mark.asyncio
async def test_builder_produces_runtime_and_context():
    from everstaff.builder.agent_builder import AgentBuilder
    from everstaff.builder.environment import TestEnvironment
    from everstaff.core.runtime import AgentRuntime
    from everstaff.core.context import AgentContext

    spec = make_minimal_spec()
    env = TestEnvironment()
    runtime, ctx = await AgentBuilder(spec, env).build()

    assert isinstance(runtime, AgentRuntime)
    assert isinstance(ctx, AgentContext)


@pytest.mark.asyncio
async def test_builder_context_has_working_memory():
    from everstaff.builder.agent_builder import AgentBuilder
    from everstaff.builder.environment import TestEnvironment
    from everstaff.protocols import Message

    spec = make_minimal_spec()
    env = TestEnvironment()
    _, ctx = await AgentBuilder(spec, env).build()

    msgs = [Message(role="user", content="test")]
    await ctx.memory.save(ctx.session_id, msgs)
    loaded = await ctx.memory.load(ctx.session_id)
    assert loaded[0].content == "test"


@pytest.mark.asyncio
async def test_test_environment_uses_in_memory_store():
    from everstaff.builder.environment import TestEnvironment
    from everstaff.nulls import InMemoryStore

    env = TestEnvironment()
    store = env.build_memory_store()
    assert isinstance(store, InMemoryStore)


def test_builder_resolves_inherit_using_parent_model_id():
    from everstaff.builder.agent_builder import AgentBuilder
    from everstaff.builder.environment import TestEnvironment
    from everstaff.schema.agent_spec import AgentSpec

    spec = AgentSpec(
        agent_name="child",
        instructions="",
        adviced_model_kind="inherit",
    )
    env = TestEnvironment()
    builder = AgentBuilder(spec, env, parent_model_id="anthropic/claude-3-haiku")
    model = builder._resolve_model()
    assert model == "anthropic/claude-3-haiku"


def test_builder_model_override_beats_inherit():
    from everstaff.builder.agent_builder import AgentBuilder
    from everstaff.builder.environment import TestEnvironment
    from everstaff.schema.agent_spec import AgentSpec

    spec = AgentSpec(
        agent_name="child",
        instructions="",
        adviced_model_kind="inherit",
        model_override="openai/gpt-4o",
    )
    env = TestEnvironment()
    builder = AgentBuilder(spec, env, parent_model_id="anthropic/claude-3-haiku")
    model = builder._resolve_model()
    assert model == "openai/gpt-4o"


def test_builder_accepts_parent_session_id():
    from everstaff.builder.agent_builder import AgentBuilder
    from everstaff.builder.environment import TestEnvironment
    from everstaff.schema.agent_spec import AgentSpec
    import asyncio

    spec = AgentSpec(agent_name="child", instructions="do stuff")
    env = TestEnvironment()
    builder = AgentBuilder(spec, env, parent_session_id="parent-123")
    _, ctx = asyncio.run(builder.build())
    assert ctx.parent_session_id == "parent-123"


def test_builder_cancellation_shared_from_parent():
    from everstaff.builder.agent_builder import AgentBuilder
    from everstaff.builder.environment import TestEnvironment
    from everstaff.schema.agent_spec import AgentSpec
    from everstaff.protocols import CancellationEvent
    import asyncio

    parent_cancel = CancellationEvent()
    spec = AgentSpec(agent_name="child", instructions="")
    env = TestEnvironment()
    builder = AgentBuilder(spec, env, parent_cancellation=parent_cancel)
    _, ctx = asyncio.run(builder.build())
    # Child shares parent's CancellationEvent
    assert ctx.cancellation is parent_cancel


def test_builder_new_cancellation_when_no_parent():
    from everstaff.builder.agent_builder import AgentBuilder
    from everstaff.builder.environment import TestEnvironment
    from everstaff.schema.agent_spec import AgentSpec
    import asyncio

    spec = AgentSpec(agent_name="root", instructions="")
    env = TestEnvironment()
    _, ctx = asyncio.run(AgentBuilder(spec, env).build())
    assert not ctx.cancellation.is_cancelled


def test_builder_registers_hitl_tool_by_default():
    """Building with a default spec (no workflow) registers the request_human_input tool."""
    from everstaff.builder.agent_builder import AgentBuilder
    from everstaff.builder.environment import TestEnvironment
    from everstaff.schema.agent_spec import AgentSpec
    from everstaff.tools.default_registry import DefaultToolRegistry
    from pathlib import Path

    spec = AgentSpec(agent_name="test-agent", instructions="do stuff")
    env = TestEnvironment()
    builder = AgentBuilder(spec, env)
    registry = builder._build_tool_registry(workdir=Path("/tmp"))
    assert registry.has_tool("request_human_input"), (
        "request_human_input should be registered by default"
    )


def test_builder_skips_hitl_tool_when_never_mode():
    """Building with hitl_mode='never' does NOT register the request_human_input tool."""
    from everstaff.builder.agent_builder import AgentBuilder
    from everstaff.builder.environment import TestEnvironment
    from everstaff.schema.agent_spec import AgentSpec
    from everstaff.tools.default_registry import DefaultToolRegistry
    from pathlib import Path

    spec = AgentSpec(agent_name="test-agent", instructions="do stuff", hitl_mode="never")
    env = TestEnvironment()
    builder = AgentBuilder(spec, env)
    registry = builder._build_tool_registry(workdir=Path("/tmp"))
    assert not registry.has_tool("request_human_input"), (
        "request_human_input should NOT be registered when hitl_mode='never'"
    )


@pytest.mark.asyncio
async def test_builder_uses_null_mcp_provider_when_no_mcp_servers():
    """When mcp_servers is empty, builder returns NullMcpProvider."""
    from everstaff.builder.agent_builder import AgentBuilder
    from everstaff.builder.environment import TestEnvironment
    from everstaff.nulls import NullMcpProvider

    spec = make_minimal_spec()
    env = TestEnvironment()
    builder = AgentBuilder(spec, env)
    provider = await builder._build_mcp_provider()

    assert isinstance(provider, NullMcpProvider)


@pytest.mark.asyncio
async def test_builder_uses_default_mcp_provider_when_mcp_servers_configured():
    """When mcp_servers is non-empty, builder instantiates DefaultMcpProvider."""
    from unittest.mock import AsyncMock, patch
    from everstaff.builder.agent_builder import AgentBuilder
    from everstaff.builder.environment import TestEnvironment
    from everstaff.schema.agent_spec import AgentSpec, MCPServerSpec
    from everstaff.mcp_client.provider import DefaultMcpProvider

    spec = AgentSpec(
        agent_name="mcp-agent",
        instructions="",
        mcp_servers=[MCPServerSpec(name="demo", command="python", args=[])],
    )
    env = TestEnvironment()
    builder = AgentBuilder(spec, env)

    with patch.object(DefaultMcpProvider, "connect_all", new_callable=AsyncMock):
        provider = await builder._build_mcp_provider()

    assert isinstance(provider, DefaultMcpProvider)


def test_builder_sub_agent_tools_have_correct_names():
    """DefaultSubAgentProvider built by AgentBuilder exposes a single delegate_task_to_subagent tool.

    When sub_agents: {one: ..., two: ...} is configured, the dict keys must be used as
    agent names (SubAgentSpec.name defaults to "" so the key must be applied). The provider
    returns one delegate_task_to_subagent tool and the prompt injection lists both agent names.
    """
    from everstaff.builder.agent_builder import AgentBuilder
    from everstaff.builder.environment import TestEnvironment
    from everstaff.schema.agent_spec import AgentSpec, SubAgentSpec
    from everstaff.protocols import CancellationEvent

    spec = AgentSpec(
        agent_name="parent",
        instructions="",
        sub_agents={
            "one": SubAgentSpec(description="Says 1", instructions="I am 1"),
            "two": SubAgentSpec(description="Says 2", instructions="I am 2"),
        },
    )
    env = TestEnvironment()
    builder = AgentBuilder(spec, env)
    cancellation = CancellationEvent()
    provider = builder._build_sub_agent_provider(
        model_id="gpt-4",
        workdir=__import__("pathlib").Path("/tmp"),
        session_id="sess-test",
        cancellation=cancellation,
    )

    tools = provider.get_tools()
    names = {t.definition.name for t in tools}
    # New architecture: one delegate_task_to_subagent tool routes to all sub-agents
    assert names == {"delegate_task_to_subagent"}, f"Expected single 'delegate_task_to_subagent' tool, got: {names}"

    # Injection must list both agent names and must not have empty agent names
    injection = provider.get_prompt_injection()
    assert "**one**" in injection, f"Injection missing 'one' agent name: {injection!r}"
    assert "**two**" in injection, f"Injection missing 'two' agent name: {injection!r}"
    assert "****: " not in injection, f"Injection has empty agent name: {injection!r}"
    # The single routing tool name must appear in the injection
    assert "delegate_task" in injection, f"Injection missing 'delegate_task' tool name: {injection!r}"


@pytest.mark.asyncio
async def test_builder_passes_max_tokens_and_temperature_to_llm_client():
    """AgentSpec.max_tokens and temperature must be forwarded to the LLM client as kwargs.

    These parameters are defined on AgentSpec but currently ignored — LiteLLM never
    receives them so the agent always uses the provider's defaults regardless of config.
    """
    from unittest.mock import patch, MagicMock
    from everstaff.builder.agent_builder import AgentBuilder
    from everstaff.builder.environment import TestEnvironment
    from everstaff.schema.agent_spec import AgentSpec

    spec = AgentSpec(
        agent_name="limited-agent",
        instructions="",
        max_tokens=512,
        temperature=0.3,
    )

    captured_kwargs: dict = {}

    class CapturingEnv(TestEnvironment):
        def build_llm_client(self, model: str, **kwargs):
            captured_kwargs.update(kwargs)
            captured_kwargs["model"] = model
            return super().build_llm_client(model, **kwargs)

    env = CapturingEnv()
    builder = AgentBuilder(spec, env)
    await builder.build()

    assert captured_kwargs.get("max_tokens") == 512, (
        f"max_tokens not passed to build_llm_client. kwargs={captured_kwargs}"
    )
    assert captured_kwargs.get("temperature") == 0.3, (
        f"temperature not passed to build_llm_client. kwargs={captured_kwargs}"
    )


@pytest.mark.asyncio
async def test_builder_sets_max_tokens_on_context():
    """AgentSpec.max_tokens must be set on AgentContext.max_tokens so runtime can persist it."""
    from everstaff.builder.agent_builder import AgentBuilder
    from everstaff.builder.environment import TestEnvironment
    from everstaff.schema.agent_spec import AgentSpec

    spec = AgentSpec(agent_name="bot", instructions="", max_tokens=256)
    env = TestEnvironment()
    _, ctx = await AgentBuilder(spec, env).build()

    assert ctx.max_tokens == 256, (
        f"AgentContext.max_tokens not set from spec. Got: {ctx.max_tokens!r}"
    )


@pytest.mark.asyncio
async def test_builder_registers_skill_use_skill_tool():
    """When agent has active skills, use_skill tool must appear in the ToolRegistry."""
    import tempfile
    from pathlib import Path
    from everstaff.builder.agent_builder import AgentBuilder
    from everstaff.builder.environment import TestEnvironment
    from everstaff.schema.agent_spec import AgentSpec
    from everstaff.core.config import FrameworkConfig
    from everstaff.schema.model_config import ModelMapping

    with tempfile.TemporaryDirectory() as tmpdir:
        skill_dir = Path(tmpdir) / "my-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: my-skill\ndescription: A skill\n---\n\nInstructions."
        )

        config = FrameworkConfig(
            model_mappings={"smart": ModelMapping(model_id="test-model")},
            skills_dirs=[tmpdir],
        )
        spec = AgentSpec(agent_name="skilled-agent", instructions="", skills=["my-skill"])
        env = TestEnvironment(config=config)
        _, ctx = await AgentBuilder(spec, env).build()

        assert ctx.tool_registry.has_tool("use_skill"), (
            "use_skill tool must be registered when agent has active skills"
        )


@pytest.mark.asyncio
async def test_builder_registers_knowledge_tools():
    """When agent has knowledge_base, search_knowledge and get_knowledge_document must be in registry."""
    import tempfile
    from pathlib import Path
    from everstaff.builder.agent_builder import AgentBuilder
    from everstaff.builder.environment import TestEnvironment
    from everstaff.schema.agent_spec import AgentSpec, KnowledgeSourceSpec

    with tempfile.TemporaryDirectory() as tmpdir:
        (Path(tmpdir) / "doc.md").write_text("# Test\n\nSome knowledge content here.")

        spec = AgentSpec(
            agent_name="knowledge-agent",
            instructions="",
            knowledge_base=[KnowledgeSourceSpec(type="local_dir", path=tmpdir)],
        )
        env = TestEnvironment()
        _, ctx = await AgentBuilder(spec, env).build()

        assert ctx.tool_registry.has_tool("search_knowledge"), (
            "search_knowledge tool must be registered when agent has knowledge_base"
        )
        assert ctx.tool_registry.has_tool("get_knowledge_document"), (
            "get_knowledge_document tool must be registered when agent has knowledge_base"
        )


@pytest.mark.asyncio
async def test_builder_registers_mcp_tools():
    """When mcp_servers is configured, MCP tools must appear in the ToolRegistry."""
    from unittest.mock import AsyncMock
    from everstaff.builder.agent_builder import AgentBuilder
    from everstaff.builder.environment import TestEnvironment
    from everstaff.schema.agent_spec import AgentSpec, MCPServerSpec
    from everstaff.mcp_client.provider import DefaultMcpProvider
    from everstaff.protocols import ToolDefinition
    from everstaff.mcp_client.tool import MCPTool

    fake_tool = MCPTool(
        session=AsyncMock(),
        definition_=ToolDefinition(name="mcp_echo", description="echo", parameters={}),
    )

    spec = AgentSpec(
        agent_name="mcp-agent",
        instructions="",
        mcp_servers=[MCPServerSpec(name="demo", command="python", args=[])],
    )
    env = TestEnvironment()
    builder = AgentBuilder(spec, env)

    # Patch _build_mcp_provider to return a provider with our fake tool
    async def _fake_build_mcp_provider():
        p = DefaultMcpProvider(spec.mcp_servers)
        p._tools = [fake_tool]
        return p

    builder._build_mcp_provider = _fake_build_mcp_provider
    _, ctx = await builder.build()

    assert ctx.tool_registry.has_tool("mcp_echo"), (
        "MCP tool 'mcp_echo' must be registered in ToolRegistry"
    )
