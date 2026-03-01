"""Tests for tools/bash.py quality fixes."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
import pytest
from unittest.mock import patch

# Add the top-level tools/ directory to sys.path so `from bash import bash` works.
_tools_dir = str(Path(__file__).parent.parent.parent / "tools")
if _tools_dir not in sys.path:
    sys.path.insert(0, _tools_dir)


@pytest.mark.asyncio
async def test_bash_returns_stdout():
    from bash import bash
    result = await bash.execute({"command": "echo hello"})
    assert "hello" in result


@pytest.mark.asyncio
async def test_bash_stderr_included_in_output():
    from bash import bash
    result = await bash.execute({"command": "echo err_message >&2"})
    assert "err_message" in result


@pytest.mark.asyncio
async def test_bash_timeout_returns_error_string():
    """On timeout, bash must return an error string (not raise)."""
    from bash import bash
    with patch("asyncio.wait_for", side_effect=asyncio.TimeoutError):
        result = await bash.execute({"command": "sleep 999"})
    assert "timeout" in result.lower() or "timed out" in result.lower()


@pytest.mark.asyncio
async def test_bash_exception_returns_error_string():
    """Generic exceptions must be caught and returned as error string (not raised)."""
    from bash import bash
    with patch("asyncio.create_subprocess_shell", side_effect=RuntimeError("test error")):
        result = await bash.execute({"command": "anything"})
    assert "error" in result.lower()
    assert "test error" in result
