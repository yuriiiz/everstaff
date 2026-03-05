"""Tests for Bash tool environment isolation."""
import os
import pytest
from pathlib import Path
from everstaff.builtin_tools.bash import make_bash_tool


@pytest.mark.asyncio
class TestBashEnvironmentIsolation:
    async def test_bash_default_clean_env(self, tmp_path):
        """Bash subprocess should NOT inherit parent os.environ by default."""
        os.environ["_TEST_SECRET_KEY"] = "super_secret_value"
        try:
            bash = make_bash_tool(tmp_path)
            result = await bash.execute({"command": "echo $_TEST_SECRET_KEY"})
            # Should be empty — clean env does not have _TEST_SECRET_KEY
            assert "super_secret_value" not in result
        finally:
            os.environ.pop("_TEST_SECRET_KEY", None)

    async def test_bash_has_minimal_env(self, tmp_path):
        """Bash subprocess should have PATH so basic commands work."""
        bash = make_bash_tool(tmp_path)
        result = await bash.execute({"command": "echo hello"})
        assert "hello" in result

    async def test_bash_printenv_is_minimal(self, tmp_path):
        """printenv should return very few variables."""
        bash = make_bash_tool(tmp_path)
        result = await bash.execute({"command": "env | wc -l"})
        # Clean env should have very few vars (PATH, HOME, maybe a few more)
        line_count = int(result.strip().split("\n")[0])
        assert line_count < 10  # Parent env typically has 30+

    async def test_bash_with_custom_env(self, tmp_path):
        """make_bash_tool should accept extra env vars."""
        extra_env = {"CUSTOM_VAR": "custom_value"}
        bash = make_bash_tool(tmp_path, env=extra_env)
        result = await bash.execute({"command": "echo $CUSTOM_VAR"})
        assert "custom_value" in result

    async def test_bash_custom_env_does_not_leak_parent(self, tmp_path):
        """Custom env should not include parent os.environ."""
        os.environ["_TEST_LEAK_CHECK"] = "should_not_appear"
        try:
            bash = make_bash_tool(tmp_path, env={"SAFE": "yes"})
            result = await bash.execute({"command": "echo $_TEST_LEAK_CHECK"})
            assert "should_not_appear" not in result
        finally:
            os.environ.pop("_TEST_LEAK_CHECK", None)
