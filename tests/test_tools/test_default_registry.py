import pytest
from everstaff.protocols import ToolDefinition, ToolResult


class FakeTool:
    def __init__(self, name: str, result: str = "ok"):
        self._name = name
        self._result = result

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self._name,
            description=f"fake {self._name}",
            parameters={"type": "object", "properties": {}},
        )

    async def execute(self, args: dict) -> ToolResult:
        return ToolResult(tool_call_id="", content=self._result)


@pytest.mark.asyncio
async def test_register_and_execute():
    from everstaff.tools.default_registry import DefaultToolRegistry
    reg = DefaultToolRegistry()
    reg.register(FakeTool("add", result="42"))
    result = await reg.execute("add", {}, tool_call_id="call_1")
    assert result.content == "42"
    assert result.tool_call_id == "call_1"


def test_get_definitions():
    from everstaff.tools.default_registry import DefaultToolRegistry
    reg = DefaultToolRegistry()
    reg.register(FakeTool("foo"))
    reg.register(FakeTool("bar"))
    defs = reg.get_definitions()
    names = {d.name for d in defs}
    assert names == {"foo", "bar"}


def test_has_tool():
    from everstaff.tools.default_registry import DefaultToolRegistry
    reg = DefaultToolRegistry()
    reg.register(FakeTool("foo"))
    assert reg.has_tool("foo")
    assert not reg.has_tool("bar")


def test_duplicate_registration_raises():
    from everstaff.tools.default_registry import DefaultToolRegistry
    reg = DefaultToolRegistry()
    reg.register(FakeTool("foo"))
    with pytest.raises(ValueError, match="already registered"):
        reg.register(FakeTool("foo"))


@pytest.mark.asyncio
async def test_execute_unknown_tool_returns_error():
    from everstaff.tools.default_registry import DefaultToolRegistry
    reg = DefaultToolRegistry()
    result = await reg.execute("ghost", {}, tool_call_id="c1")
    assert result.is_error
    assert "ghost" in result.content
