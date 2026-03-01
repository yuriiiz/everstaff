"""API hitl.py must delegate to everstaff.hitl.resolve.resolve_hitl."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import json


@pytest.mark.asyncio
async def test_resolve_hitl_internal_calls_canonical():
    """_resolve_hitl_internal must call canonical resolve_hitl."""
    from everstaff.api.hitl import _resolve_hitl_internal

    app = MagicMock()
    app.state.file_store = MagicMock()
    app.state.config = MagicMock()

    session_data = {
        "session_id": "sess-1",
        "agent_name": "test-agent",
        "hitl_requests": [{"hitl_id": "h-1", "status": "pending"}],
    }

    with patch("everstaff.api.hitl.canonical_resolve", new_callable=AsyncMock) as mock_resolve, \
         patch("everstaff.api.hitl._find_hitl_in_sessions", new_callable=AsyncMock) as mock_find:
        mock_find.return_value = ("sess-1", {"hitl_id": "h-1", "status": "pending"}, session_data)
        mock_resolve.return_value = MagicMock(decision="approved")

        # Also need to mock the re-read for all_settled check
        with patch("everstaff.api.hitl.all_hitls_settled", return_value=False):
            await _resolve_hitl_internal(app, "h-1", "approved")

        mock_resolve.assert_called_once()
        call_kwargs = mock_resolve.call_args
        assert call_kwargs.kwargs.get("session_id") == "sess-1" or call_kwargs[1].get("session_id") == "sess-1"


def test_hitl_module_imports_canonical():
    """hitl.py must import from everstaff.hitl.resolve."""
    import inspect
    import everstaff.api.hitl as mod
    source = inspect.getsource(mod)
    assert "from everstaff.hitl.resolve import" in source or "everstaff.hitl.resolve" in source, \
        "hitl.py must import canonical resolve function"
