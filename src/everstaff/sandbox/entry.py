"""Sandbox process entry point.

This module is the main() for a sandbox subprocess. It:
1. Connects to orchestrator via IPC channel
2. Authenticates with ephemeral token and receives secrets
3. Builds SandboxEnvironment with proxy adapters
4. Runs AgentRuntime with the provided agent spec
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from everstaff.core.secret_store import SecretStore
from everstaff.protocols import CancellationEvent
from everstaff.sandbox.environment import SandboxEnvironment
from everstaff.sandbox.ipc.unix_socket import UnixSocketChannel

logger = logging.getLogger(__name__)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Everstaff sandbox process")
    parser.add_argument("--socket-path", required=True, help="IPC socket path")
    parser.add_argument("--token", required=True, help="Ephemeral auth token")
    parser.add_argument("--session-id", required=True, help="Session ID")
    parser.add_argument("--agent-spec", default=None, help="Agent spec JSON string")
    parser.add_argument("--params-file", default=None, help="JSON file with agent_spec and user_input")
    parser.add_argument("--workspace-dir", default="/work", help="Workspace directory")
    parser.add_argument("--user-input", default=None, help="Initial user input text")
    return parser.parse_args(argv)


async def sandbox_main(
    socket_path: str,
    token: str,
    session_id: str,
    agent_spec_json: str,
    workspace_dir: str,
    user_input: str | None = None,
) -> None:
    """Entry point for sandbox process."""
    # 1. Connect and authenticate
    channel = UnixSocketChannel()
    await channel.connect(socket_path)

    try:
        auth_result = await channel.send_request("auth", {"token": token})
        secret_store = SecretStore(auth_result.get("secrets", {}))

        # Bridge SecretStore to litellm so LLM calls can find API keys
        # without leaking them to os.environ.
        from everstaff.llm.secret_bridge import install_secret_bridge
        install_secret_bridge(secret_store)

        # Parse config from orchestrator
        from everstaff.core.config import FrameworkConfig
        config_data = auth_result.get("config", {})
        config = FrameworkConfig(**config_data) if config_data else None

        # 2. Build environment
        workspace = Path(workspace_dir)
        workspace.mkdir(parents=True, exist_ok=True)
        env = SandboxEnvironment(
            channel=channel,
            secret_store=secret_store,
            workspace_dir=workspace,
            config=config,
        )

        # 3. Shared cancellation event for the agent call tree
        cancellation = CancellationEvent()

        # Register cancel handler — triggers CancellationEvent so the
        # AgentRuntime's polling loop (_is_cancelled) picks it up.
        async def _on_cancel(params):
            force = params.get("force", False) if isinstance(params, dict) else False
            cancellation.cancel(force=force)
            logger.info("Cancel received for session %s (force=%s)", session_id, force)

        channel.on_push("cancel", _on_cancel)

        # 4. Register HITL resolution handler
        _hitl_resolutions: asyncio.Queue = asyncio.Queue()

        async def _on_hitl_resolution(params):
            _hitl_resolutions.put_nowait(params)

        channel.on_push("hitl.resolution", _on_hitl_resolution)

        # 5. Run agent
        await _run_agent(
            env=env,
            session_id=session_id,
            agent_spec_json=agent_spec_json,
            cancellation=cancellation,
            hitl_resolutions=_hitl_resolutions,
            channel=channel,
            user_input=user_input,
        )
    finally:
        await channel.close()


async def _run_agent(
    env: SandboxEnvironment,
    session_id: str,
    agent_spec_json: str,
    cancellation: CancellationEvent,
    hitl_resolutions: asyncio.Queue,
    channel: UnixSocketChannel | None = None,
    user_input: str | None = None,
) -> None:
    """Build and run AgentRuntime. Separated for testability."""
    from everstaff.builder.agent_builder import AgentBuilder
    from everstaff.schema.agent_spec import AgentSpec

    spec = AgentSpec.model_validate_json(agent_spec_json)
    builder = AgentBuilder(
        spec, env, session_id=session_id, parent_cancellation=cancellation,
        user_input=user_input,
    )
    runtime, ctx = await builder.build()

    try:
        async for event in runtime.run_stream(user_input):
            if channel is not None:
                try:
                    await channel.send_notification(
                        "stream.event",
                        {**event.model_dump(), "session_id": session_id},
                    )
                except Exception:
                    pass  # fire-and-forget
    finally:
        # Clean up MCP connections to avoid async generator warnings
        if hasattr(ctx.mcp_provider, "aclose"):
            try:
                await ctx.mcp_provider.aclose()
            except Exception:
                pass


def main() -> None:
    """CLI entry point: python -m everstaff.sandbox.entry"""
    import json as _json
    import os as _os
    from everstaff.utils.logging import setup_logging
    setup_logging(console=True, level=_os.getenv("LOG_LEVEL", "INFO"))

    args = parse_args()

    agent_spec_json = args.agent_spec or "{}"
    user_input = args.user_input

    # Prefer params file over CLI args (avoids OS arg-length limits)
    if args.params_file:
        with open(args.params_file) as f:
            params = _json.load(f)
        agent_spec_json = params.get("agent_spec", "{}")
        user_input = params.get("user_input", user_input)

    asyncio.run(sandbox_main(
        socket_path=args.socket_path,
        token=args.token,
        session_id=args.session_id,
        agent_spec_json=agent_spec_json,
        workspace_dir=args.workspace_dir,
        user_input=user_input,
    ))


if __name__ == "__main__":
    main()
