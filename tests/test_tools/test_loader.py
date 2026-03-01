"""Tests for filesystem-based tool loader."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from everstaff.tools.loader import ToolLoader
from everstaff.tools.manager import ToolManager


@pytest.fixture()
def tools_dir(tmp_path: Path) -> Path:
    """Create a temporary tools directory with sample tool files."""
    d = tmp_path / "tools"
    d.mkdir()

    # Valid tool: single tool per file
    (d / "hello.py").write_text(
        textwrap.dedent("""\
        from everstaff.tools.native import tool

        @tool(name="Hello", description="Say hello")
        def hello(name: str = "World") -> str:
            return f"Hello, {name}!"

        TOOLS = [hello]
        """)
    )

    # Valid tool: multiple tools per file
    (d / "math_tools.py").write_text(
        textwrap.dedent("""\
        from everstaff.tools.native import tool

        @tool(name="Add", description="Add two numbers")
        def add(a: int, b: int) -> int:
            return a + b

        @tool(name="Multiply", description="Multiply two numbers")
        def multiply(a: int, b: int) -> int:
            return a * b

        TOOLS = [add, multiply]
        """)
    )

    # File without TOOLS — should be skipped silently
    (d / "no_tools.py").write_text(
        textwrap.dedent("""\
        def helper():
            pass
        """)
    )

    # File starting with _ — should be skipped
    (d / "_private.py").write_text(
        textwrap.dedent("""\
        from everstaff.tools.native import tool

        @tool(name="Secret", description="Secret tool")
        def secret() -> str:
            return "secret"

        TOOLS = [secret]
        """)
    )

    return d


class TestDiscover:
    def test_discovers_tools(self, tools_dir: Path):
        mgr = ToolManager([str(tools_dir)])
        available = mgr.discover()
        assert "Hello" in available
        assert "Add" in available
        assert "Multiply" in available

    def test_skips_underscore_files(self, tools_dir: Path):
        mgr = ToolManager([str(tools_dir)])
        available = mgr.discover()
        assert "Secret" not in available

    def test_skips_files_without_tools(self, tools_dir: Path):
        mgr = ToolManager([str(tools_dir)])
        available = mgr.discover()
        # no_tools.py has no TOOLS list — should not appear
        assert len(available) == 3  # Hello, Add, Multiply

    def test_available_tools_sorted(self, tools_dir: Path):
        mgr = ToolManager([str(tools_dir)])
        names = sorted(mgr.discover().keys())
        assert names == ["Add", "Hello", "Multiply"]

    def test_nonexistent_dir_ignored(self, tmp_path: Path):
        mgr = ToolManager([str(tmp_path / "nonexistent")])
        available = mgr.discover()
        assert available == {}

    def test_empty_dir(self, tmp_path: Path):
        d = tmp_path / "empty"
        d.mkdir()
        mgr = ToolManager([str(d)])
        available = mgr.discover()
        assert available == {}


class TestLoad:
    def test_load_specific_tools(self, tools_dir: Path):
        loader = ToolLoader([str(tools_dir)])
        tools = loader.load(["Hello", "Add"])
        names = {t.definition.name for t in tools}
        assert names == {"Hello", "Add"}

    def test_load_missing_tool_warns(self, tools_dir: Path, caplog):
        loader = ToolLoader([str(tools_dir)])
        tools = loader.load(["Hello", "NonExistent"])
        # Should still return the found tool
        assert len(tools) == 1
        assert tools[0].definition.name == "Hello"

    def test_load_empty_list(self, tools_dir: Path):
        loader = ToolLoader([str(tools_dir)])
        tools = loader.load([])
        assert tools == []


class TestExecution:
    def test_loaded_tool_executes(self, tools_dir: Path):
        loader = ToolLoader([str(tools_dir)])
        tools = loader.load(["Hello"])
        hello = tools[0]
        import asyncio
        result = asyncio.run(hello.execute({"name": "Test"}))
        assert result == "Hello, Test!"

    def test_loaded_math_tool_executes(self, tools_dir: Path):
        loader = ToolLoader([str(tools_dir)])
        tools = loader.load(["Add"])
        add = tools[0]
        import asyncio
        result = asyncio.run(add.execute({"a": 3, "b": 7}))
        assert result == "10"


class TestToolsFactory:
    def test_tools_factory_only_discoverable(self, tmp_path: Path):
        """A file with only TOOLS_FACTORY (no TOOLS) must be discoverable via scan_dir."""
        d = tmp_path / "tools"
        d.mkdir()
        (d / "factory_only.py").write_text(
            textwrap.dedent("""\
            from pathlib import Path
            from everstaff.tools.native import tool

            def make_factory_tool(workdir: Path):
                @tool(name="FactoryTool", description="Tool via factory only")
                def factory_tool(arg: str) -> str:
                    return f"result: {arg}"
                return factory_tool

            TOOLS_FACTORY = make_factory_tool
            """)
        )
        mgr = ToolManager([str(d)])
        discovered = mgr.discover()
        assert "FactoryTool" in discovered

    def test_tools_factory_only_has_correct_params(self, tmp_path: Path):
        """TOOLS_FACTORY-only discovery must extract parameters from @tool decorator."""
        d = tmp_path / "tools"
        d.mkdir()
        (d / "factory_params.py").write_text(
            textwrap.dedent("""\
            from pathlib import Path
            from everstaff.tools.native import tool

            def make_param_tool(workdir: Path):
                @tool(name="ParamTool", description="Tool with params")
                def param_tool(file_path: str, offset: int = 0) -> str:
                    return ""
                return param_tool

            TOOLS_FACTORY = make_param_tool
            """)
        )
        mgr = ToolManager([str(d)])
        discovered = mgr.discover()
        assert "ParamTool" in discovered
        defn = discovered["ParamTool"][1].definition
        param_names = [p.name for p in defn.parameters]
        assert "file_path" in param_names
        assert "offset" in param_names

    def test_tools_list_callable_factory(self, tmp_path: Path):
        """TOOLS list items that are callable factories are handled via Path('.') call."""
        d = tmp_path / "tools"
        d.mkdir()
        (d / "callable_factory.py").write_text(
            textwrap.dedent("""\
            from pathlib import Path
            from everstaff.tools.native import tool

            def make_callable_tool(workdir: Path):
                @tool(name="CallableTool", description="Callable factory in TOOLS")
                def callable_tool(x: str) -> str:
                    return x
                return callable_tool

            TOOLS = [make_callable_tool]
            """)
        )
        mgr = ToolManager([str(d)])
        discovered = mgr.discover()
        assert "CallableTool" in discovered


def test_real_tools_load(tmp_path):
    """Glob, Grep, and Read tool files must import without errors."""
    import importlib.util
    from pathlib import Path
    tools_root = Path(__file__).parents[2] / "tools"
    for name in ("glob_tool", "grep_tool", "read"):
        py = tools_root / f"{name}.py"
        assert py.exists(), f"Expected tool file not found: {py}"
        spec = importlib.util.spec_from_file_location(f"_test_{name}", py)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)   # must not raise
        assert hasattr(mod, "TOOLS"), f"{name}.py missing TOOLS"
        assert len(mod.TOOLS) > 0


class TestMultipleDirs:
    def test_multiple_dirs(self, tmp_path: Path):
        dir1 = tmp_path / "dir1"
        dir2 = tmp_path / "dir2"
        dir1.mkdir()
        dir2.mkdir()

        (dir1 / "tool_a.py").write_text(
            textwrap.dedent("""\
            from everstaff.tools.native import tool

            @tool(name="ToolA", description="A")
            def tool_a() -> str:
                return "A"

            TOOLS = [tool_a]
            """)
        )
        (dir2 / "tool_b.py").write_text(
            textwrap.dedent("""\
            from everstaff.tools.native import tool

            @tool(name="ToolB", description="B")
            def tool_b() -> str:
                return "B"

            TOOLS = [tool_b]
            """)
        )

        loader = ToolLoader([str(dir1), str(dir2)])
        tools = loader.load(["ToolA", "ToolB"])
        names = {t.definition.name for t in tools}
        assert names == {"ToolA", "ToolB"}
