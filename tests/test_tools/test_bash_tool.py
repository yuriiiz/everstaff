"""Tests for tools/bash.py quality fixes."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
import pytest
from unittest.mock import patch

# Add the builtin_tools directory to sys.path so `from bash import bash` works.
_tools_dir = str(Path(__file__).parent.parent.parent / "src" / "everstaff" / "builtin_tools")
if _tools_dir not in sys.path:
    sys.path.insert(0, _tools_dir)


def _get_bash_tool():
    from everstaff.builtin_tools import bash as bash_mod
    return bash_mod.TOOLS[0]


@pytest.mark.asyncio
async def test_bash_returns_stdout():
    bash = _get_bash_tool()
    result = await bash.execute({"command": "echo hello"})
    assert "hello" in result


@pytest.mark.asyncio
async def test_bash_stderr_included_in_output():
    bash = _get_bash_tool()
    result = await bash.execute({"command": "echo err_message >&2"})
    assert "err_message" in result


@pytest.mark.asyncio
async def test_bash_timeout_returns_error_string():
    """On timeout, bash must return an error string (not raise)."""
    bash = _get_bash_tool()
    with patch("asyncio.wait_for", side_effect=asyncio.TimeoutError):
        result = await bash.execute({"command": "sleep 999"})
    assert "timeout" in result.lower() or "timed out" in result.lower()


@pytest.mark.asyncio
async def test_bash_exception_returns_error_string():
    """Generic exceptions must be caught and returned as error string (not raised)."""
    bash = _get_bash_tool()
    with patch("asyncio.create_subprocess_shell", side_effect=RuntimeError("test error")):
        result = await bash.execute({"command": "anything"})
    assert "error" in result.lower()
    assert "test error" in result


@pytest.mark.asyncio
async def test_bash_custom_timeout_accepted():
    """Bash tool accepts a custom timeout parameter."""
    bash = _get_bash_tool()
    # A fast command with custom timeout should succeed normally
    result = await bash.execute({"command": "echo ok", "timeout": 60})
    assert "ok" in result


@pytest.mark.asyncio
async def test_bash_timeout_clamped_minimum():
    """Timeout below 10s is clamped to 10s."""
    bash = _get_bash_tool()
    result = await bash.execute({"command": "echo clamped", "timeout": 1})
    # Should not error — clamped to 10s, fast command finishes before that
    assert "clamped" in result


@pytest.mark.asyncio
async def test_bash_timeout_clamped_maximum():
    """Timeout above 3600s is clamped to 3600s."""
    bash = _get_bash_tool()
    result = await bash.execute({"command": "echo maxed", "timeout": 99999})
    assert "maxed" in result


@pytest.mark.asyncio
async def test_bash_timeout_error_shows_custom_value():
    """Timeout error message reflects the custom timeout value."""
    bash = _get_bash_tool()
    # Mock to simulate timeout at the clamped value
    with patch("asyncio.wait_for", side_effect=asyncio.TimeoutError):
        result = await bash.execute({"command": "sleep 999", "timeout": 600})
    assert "600" in result
